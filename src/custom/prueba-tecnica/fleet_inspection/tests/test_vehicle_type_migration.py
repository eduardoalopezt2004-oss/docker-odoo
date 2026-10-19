from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import sql

from odoo.addons.fleet_inspection.tools.vehicle_type_migration import (
    LEGACY_COLUMN,
    LEGACY_XMLIDS,
    map_legacy_vehicle_types,
    preserve_legacy_vehicle_type,
)


@tagged("post_install", "-at_install")
class TestVehicleTypeMigration(TransactionCase):
    """Lógica de los scripts de migrations/18.0.1.1.0, probada sin ejecutar -u.

    Cada prueba deja la tabla como queda a mitad de una actualización desde la
    18.0.1.0.0: el valor viejo en vehicle_type_legacy y el campo nuevo con el valor
    por defecto (Carro), que es lo que Odoo pone en las filas existentes de una
    columna requerida nueva.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Marca de prueba"})
        model = cls.env["fleet.vehicle.model"].create({"name": "Modelo de prueba", "brand_id": brand.id})
        vehicle = cls.env["fleet.vehicle"].create({"model_id": model.id, "license_plate": "MIG001"})
        cls.car = cls.env.ref("fleet_inspection.vehicle_type_car")
        Inspection = cls.env["fleet.inspection"]
        cls.inspection_by_legacy = {
            legacy: Inspection.create({"vehicle_id": vehicle.id, "vehicle_type": cls.car.id})
            for legacy in LEGACY_XMLIDS
        }
        cls.env.flush_all()
        cls.env.cr.execute("ALTER TABLE fleet_inspection ADD COLUMN IF NOT EXISTS vehicle_type_legacy varchar")
        for legacy, inspection in cls.inspection_by_legacy.items():
            cls._set_legacy(inspection, legacy)

    @classmethod
    def _set_legacy(cls, inspection, value):
        cls.env.cr.execute(
            "UPDATE fleet_inspection SET vehicle_type_legacy = %s WHERE id = %s", (value, inspection.id)
        )

    def _types(self):
        self.env.invalidate_all()
        return {legacy: inspection.vehicle_type for legacy, inspection in self.inspection_by_legacy.items()}

    def test_maps_every_value_including_other(self):
        updated = map_legacy_vehicle_types(self.env)
        expected = {legacy: self.env.ref(xmlid) for legacy, xmlid in LEGACY_XMLIDS.items()}
        self.assertEqual(self._types(), expected)
        self.assertEqual(self._types()["other"].name, "Otro")
        # Carro ya tenía el valor por defecto correcto: cambian moto, camión y otro.
        self.assertEqual(updated, 3)

    def test_running_twice_changes_nothing(self):
        map_legacy_vehicle_types(self.env)
        after_first = self._types()
        self.assertEqual(map_legacy_vehicle_types(self.env), 0)
        self.assertEqual(self._types(), after_first)

    def test_unknown_value_stops_migration(self):
        self._set_legacy(self.inspection_by_legacy["truck"], "van")
        with self.assertRaises(UserError) as error:
            map_legacy_vehicle_types(self.env)
        self.assertIn("van", str(error.exception))
        # Nada se mapeó: la moto sigue con el valor por defecto.
        self.assertEqual(self._types()["motorcycle"], self.car)

    def test_inspection_without_any_type_stops_migration(self):
        self.env.cr.execute("ALTER TABLE fleet_inspection ALTER COLUMN vehicle_type DROP NOT NULL")
        self.env.cr.execute(
            "UPDATE fleet_inspection SET vehicle_type = NULL, vehicle_type_legacy = NULL WHERE id = %s",
            (self.inspection_by_legacy["truck"].id,),
        )
        with self.assertRaises(UserError):
            map_legacy_vehicle_types(self.env)

    def test_inspections_created_after_migration_are_left_alone(self):
        """Una inspección nueva no tiene valor viejo pero sí tipo: no es un error."""
        truck = self.env.ref("fleet_inspection.vehicle_type_truck")
        new = self.env["fleet.inspection"].create(
            {"vehicle_id": self.inspection_by_legacy["car"].vehicle_id.id, "vehicle_type": truck.id}
        )
        map_legacy_vehicle_types(self.env)
        self.env.invalidate_all()
        self.assertEqual(new.vehicle_type, truck)

    def test_preserve_renames_selection_column_once(self):
        cr = self.env.cr
        cr.execute("CREATE TABLE fleet_inspection_pre_test (id serial PRIMARY KEY, vehicle_type varchar)")
        cr.execute("INSERT INTO fleet_inspection_pre_test (vehicle_type) VALUES ('motorcycle'), ('other')")
        self.assertTrue(preserve_legacy_vehicle_type(cr, "fleet_inspection_pre_test"))
        self.assertFalse(sql.column_exists(cr, "fleet_inspection_pre_test", "vehicle_type"))
        cr.execute("SELECT vehicle_type_legacy FROM fleet_inspection_pre_test ORDER BY id")
        self.assertEqual([row[0] for row in cr.fetchall()], ["motorcycle", "other"])
        # Segunda ejecución: ya está hecho, no toca nada.
        self.assertFalse(preserve_legacy_vehicle_type(cr, "fleet_inspection_pre_test"))

    def test_preserve_skips_column_already_many2one(self):
        """Base instalada directamente en 18.0.1.1.0: no hay nada que preservar."""
        cr = self.env.cr
        cr.execute("ALTER TABLE fleet_inspection DROP COLUMN vehicle_type_legacy")
        self.assertFalse(preserve_legacy_vehicle_type(cr))
        self.assertEqual(sql.table_columns(cr, "fleet_inspection")["vehicle_type"]["udt_name"], "int4")
        self.assertFalse(sql.column_exists(cr, "fleet_inspection", LEGACY_COLUMN))
