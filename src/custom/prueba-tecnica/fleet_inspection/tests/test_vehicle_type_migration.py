from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import SQL, sql

from odoo.addons.fleet_inspection.tools.vehicle_type_migration import (
    DEFAULT_BATCH_SIZE,
    LEGACY_COLUMN,
    LEGACY_XMLIDS,
    map_legacy_vehicle_types,
    preserve_legacy_vehicle_type,
)

MIGRATION_LOGGER = "odoo.addons.fleet_inspection.tools.vehicle_type_migration"


@tagged("post_install", "-at_install")
class TestVehicleTypeMigration(TransactionCase):
    """Lógica de los scripts de migrations/18.0.1.1.0, probada sin ejecutar -u.

    Cada prueba deja la tabla como queda a mitad de una actualización desde la
    18.0.1.0.0: el valor viejo en vehicle_type_legacy y el campo nuevo vacío
    (Odoo calcula el valor por defecto antes de cargar el catálogo).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Marca de prueba"})
        model = cls.env["fleet.vehicle.model"].create({"name": "Modelo de prueba", "brand_id": brand.id})
        cls.vehicle = cls.env["fleet.vehicle"].create({"model_id": model.id, "license_plate": "MIG001"})
        Inspection = cls.env["fleet.inspection"]
        cls.inspection_by_legacy = {legacy: Inspection.create({"vehicle_id": cls.vehicle.id}) for legacy in LEGACY_XMLIDS}
        cls.env.flush_all()
        cr = cls.env.cr
        cr.execute("ALTER TABLE fleet_inspection ADD COLUMN IF NOT EXISTS vehicle_type_legacy varchar")
        cr.execute("ALTER TABLE fleet_inspection ALTER COLUMN vehicle_type DROP NOT NULL")
        for legacy, inspection in cls.inspection_by_legacy.items():
            cr.execute(
                "UPDATE fleet_inspection SET vehicle_type = NULL, vehicle_type_legacy = %s WHERE id = %s",
                (legacy, inspection.id),
            )
        cls.env.invalidate_all()

    def _types(self):
        self.env.invalidate_all()
        return {legacy: inspection.vehicle_type for legacy, inspection in self.inspection_by_legacy.items()}

    def test_maps_every_value_including_other(self):
        updated = map_legacy_vehicle_types(self.env)
        expected = {legacy: self.env.ref(xmlid) for legacy, xmlid in LEGACY_XMLIDS.items()}
        self.assertEqual(self._types(), expected)
        self.assertEqual(self._types()["other"].name, "Otro")
        self.assertEqual(updated, 4)

    def test_running_twice_changes_nothing(self):
        map_legacy_vehicle_types(self.env)
        after_first = self._types()
        self.assertEqual(map_legacy_vehicle_types(self.env), 0)
        self.assertEqual(self._types(), after_first)

    def test_type_changed_after_migration_is_kept(self):
        """Ejecutarla otra vez no devuelve al tipo viejo lo que alguien cambió después."""
        map_legacy_vehicle_types(self.env)
        truck = self.env.ref("fleet_inspection.vehicle_type_truck")
        self.inspection_by_legacy["motorcycle"].vehicle_type = truck
        map_legacy_vehicle_types(self.env)
        self.assertEqual(self._types()["motorcycle"], truck)

    def test_unknown_value_stops_migration(self):
        self.env.cr.execute(
            "UPDATE fleet_inspection SET vehicle_type_legacy = 'van' WHERE id = %s",
            (self.inspection_by_legacy["truck"].id,),
        )
        with self.assertRaises(UserError) as error:
            map_legacy_vehicle_types(self.env)
        self.assertIn("van", str(error.exception))
        # Se detuvo antes de asignar: la moto sigue sin tipo.
        self.assertFalse(self._types()["motorcycle"])

    def test_inspection_without_any_type_stops_migration(self):
        self.env.cr.execute(
            "UPDATE fleet_inspection SET vehicle_type_legacy = NULL WHERE id = %s",
            (self.inspection_by_legacy["truck"].id,),
        )
        with self.assertRaises(UserError):
            map_legacy_vehicle_types(self.env)

    def test_missing_backup_with_empty_types_stops_migration(self):
        """Si el pre-migrate no guardó el valor viejo, no se termina con inspecciones sin tipo."""
        self.env.cr.execute("ALTER TABLE fleet_inspection DROP COLUMN vehicle_type_legacy")
        with self.assertRaises(UserError):
            map_legacy_vehicle_types(self.env)

    def test_inspections_created_after_migration_are_left_alone(self):
        """Una inspección nueva no tiene valor viejo pero sí tipo: no es un error."""
        truck = self.env.ref("fleet_inspection.vehicle_type_truck")
        new = self.env["fleet.inspection"].create({"vehicle_id": self.vehicle.id, "vehicle_type": truck.id})
        map_legacy_vehicle_types(self.env)
        self.env.invalidate_all()
        self.assertEqual(new.vehicle_type, truck)

    def test_preserve_renames_selection_column_once(self):
        cr = self.env.cr
        for column_type in ("varchar", "text"):
            table = "fleet_inspection_pre_test_%s" % column_type
            cr.execute(
                SQL("CREATE TABLE %s (id serial PRIMARY KEY, vehicle_type %s)", SQL.identifier(table), SQL(column_type))
            )
            cr.execute(SQL("INSERT INTO %s (vehicle_type) VALUES ('motorcycle'), ('other')", SQL.identifier(table)))
            self.assertTrue(preserve_legacy_vehicle_type(cr, table))
            self.assertFalse(sql.column_exists(cr, table, "vehicle_type"))
            cr.execute(SQL("SELECT vehicle_type_legacy FROM %s ORDER BY id", SQL.identifier(table)))
            self.assertEqual([row[0] for row in cr.fetchall()], ["motorcycle", "other"])
            # Segunda ejecución: ya está hecho, no toca nada.
            self.assertFalse(preserve_legacy_vehicle_type(cr, table))

    def test_preserve_skips_column_already_many2one(self):
        """Base instalada directamente en 18.0.1.1.0: no hay nada que preservar."""
        cr = self.env.cr
        cr.execute("ALTER TABLE fleet_inspection DROP COLUMN vehicle_type_legacy")
        self.assertFalse(preserve_legacy_vehicle_type(cr))
        self.assertEqual(sql.table_columns(cr, "fleet_inspection")["vehicle_type"]["udt_name"], "int4")
        self.assertFalse(sql.column_exists(cr, "fleet_inspection", LEGACY_COLUMN))

    # Tramo C: procesamiento por lotes

    def _add_legacy_inspections(self, legacy_values):
        """Inspecciones extra en el estado de mitad de actualización, con el valor viejo dado."""
        inspections = self.env["fleet.inspection"].create([{"vehicle_id": self.vehicle.id} for _ in legacy_values])
        self.env.flush_all()
        for inspection, legacy in zip(inspections, legacy_values):
            self.env.cr.execute(
                "UPDATE fleet_inspection SET vehicle_type = NULL, vehicle_type_legacy = %s WHERE id = %s",
                (legacy, inspection.id),
            )
        self.env.invalidate_all()
        return inspections

    def test_default_batch_size(self):
        self.assertEqual(DEFAULT_BATCH_SIZE, 1000)

    def test_small_batches_give_same_result(self):
        """Lotes de una sola inspección dan lo mismo que un solo lote."""
        updated = map_legacy_vehicle_types(self.env, batch_size=1)
        self.assertEqual(updated, 4)
        expected = {legacy: self.env.ref(xmlid) for legacy, xmlid in LEGACY_XMLIDS.items()}
        self.assertEqual(self._types(), expected)

    def test_batches_cover_every_row_and_count_batches(self):
        """33 inspecciones sin tipo (4 de setUpClass y 29 nuevas) en lotes de 7: 5 lotes, ninguna queda sin tipo."""
        legacy_values = list(LEGACY_XMLIDS) * 7 + ["car"]
        self.assertEqual(len(legacy_values), 29)
        extra = self._add_legacy_inspections(legacy_values)
        with self.assertLogs(MIGRATION_LOGGER, level="INFO") as logs:
            updated = map_legacy_vehicle_types(self.env, batch_size=7)
        self.assertEqual(updated, 33)
        self.assertIn("en 5 lotes de hasta 7", "\n".join(logs.output))
        self.env.invalidate_all()
        for inspection, legacy in zip(extra, legacy_values):
            self.assertEqual(inspection.vehicle_type, self.env.ref(LEGACY_XMLIDS[legacy]))

    def test_batches_skip_rows_that_already_have_a_type(self):
        """Una fila con tipo entre filas sin tipo no se toca, aunque caiga dentro de un lote."""
        truck = self.env.ref("fleet_inspection.vehicle_type_truck")
        self.env.cr.execute(
            "UPDATE fleet_inspection SET vehicle_type = %s WHERE id = %s",
            (truck.id, self.inspection_by_legacy["car"].id),
        )
        self.env.invalidate_all()
        updated = map_legacy_vehicle_types(self.env, batch_size=2)
        self.assertEqual(updated, 3)
        self.assertEqual(self._types()["car"], truck)
        self.assertEqual(self._types()["other"], self.env.ref("fleet_inspection.vehicle_type_other"))

    def test_second_run_in_batches_changes_nothing(self):
        map_legacy_vehicle_types(self.env, batch_size=3)
        after_first = self._types()
        with self.assertLogs(MIGRATION_LOGGER, level="INFO") as logs:
            self.assertEqual(map_legacy_vehicle_types(self.env, batch_size=3), 0)
        self.assertEqual(self._types(), after_first)
        self.assertIn("en 0 lotes", "\n".join(logs.output))

    def test_batch_size_must_be_positive(self):
        for batch_size in (0, -1):
            with self.subTest(batch_size=batch_size), self.assertRaises(ValueError):
                map_legacy_vehicle_types(self.env, batch_size=batch_size)
        # No asignó nada antes de rechazar el tamaño de lote.
        self.assertFalse(self._types()["motorcycle"])

    def test_log_reports_time_and_memory(self):
        """El registro deja el tiempo y la memoria máxima del proceso, para medir en una base real."""
        with self.assertLogs(MIGRATION_LOGGER, level="INFO") as logs:
            map_legacy_vehicle_types(self.env)
        output = "\n".join(logs.output)
        self.assertRegex(output, r"en \d+(\.\d+)? s")
        self.assertIn("memoria máxima del proceso", output)

