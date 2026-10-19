"""Paso del tipo de vehículo de selección a catálogo (18.0.1.0.0 -> 18.0.1.1.0).

Lo llaman migrations/18.0.1.1.0/pre-migrate.py y post-migrate.py. Vive aquí y no
en los scripts para poder probarlo sin ejecutar -u.
"""

import logging
import time

from odoo.exceptions import UserError
from odoo.tools import SQL, sql

try:
    import resource
except ImportError:  # Windows: sin dato de memoria en el registro.
    resource = None

_logger = logging.getLogger(__name__)

LEGACY_COLUMN = "vehicle_type_legacy"
# Inspecciones que toca cada sentencia UPDATE.
DEFAULT_BATCH_SIZE = 1000

# Valor de la selección en 18.0.1.0.0 -> registro del catálogo. Ningún valor
# queda sin destino, incluido "other".
LEGACY_XMLIDS = {
    "motorcycle": "fleet_inspection.vehicle_type_motorcycle",
    "car": "fleet_inspection.vehicle_type_car",
    "truck": "fleet_inspection.vehicle_type_truck",
    "other": "fleet_inspection.vehicle_type_other",
}


def preserve_legacy_vehicle_type(cr, table="fleet_inspection"):
    """Guarda el valor viejo antes de que el ORM cambie la columna (pre-migrate).

    Renombra la columna de texto vehicle_type a vehicle_type_legacy. Si se dejara
    con su nombre, el ORM intentaría convertir 'car' a entero y la actualización
    fallaría. Ningún campo usa la columna renombrada, así que Odoo no la convierte
    ni la borra.

    :return: True si renombró; False si no había nada que hacer (ya estaba hecho
        o la columna ya es el many2one).
    """
    if sql.column_exists(cr, table, LEGACY_COLUMN):
        return False
    column = sql.table_columns(cr, table).get("vehicle_type")
    if not column or column["udt_name"] not in ("varchar", "text"):
        return False
    sql.rename_column(cr, table, "vehicle_type", LEGACY_COLUMN)
    _logger.info("%s.vehicle_type renombrada a %s antes de la migración", table, LEGACY_COLUMN)
    return True


def _max_memory_mb():
    """Memoria máxima (RSS) que usó el proceso hasta ahora, en MB; None si no se puede medir."""
    if resource is None:
        return None
    # En Linux ru_maxrss viene en KB.
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)


def map_legacy_vehicle_types(env, batch_size=DEFAULT_BATCH_SIZE):
    """Asigna a cada inspección sin tipo el del catálogo según su valor viejo (post-migrate).

    Durante la actualización las inspecciones existentes llegan con el tipo vacío:
    Odoo calcula el valor por defecto de la columna nueva antes de cargar el
    catálogo. Solo se completan esas; un tipo ya puesto no se toca, así que
    ejecutar la función otra vez no deshace cambios hechos después de migrar.

    Recorre las inspecciones sin tipo en orden de id, de a ``batch_size``: cada
    UPDATE toca a lo sumo ese número de filas, y Python solo guarda el último id
    procesado, así que la memoria no crece con el tamaño de la tabla. Todo ocurre
    dentro de la transacción de la actualización: si algo falla, se deshace completa.

    Detiene la actualización si hay valores viejos sin destino en el catálogo o si
    al final queda alguna inspección sin tipo.

    :param batch_size: inspecciones por lote, mayor que 0.
    :return: cantidad de inspecciones a las que se les asignó tipo.
    """
    if batch_size < 1:
        raise ValueError("batch_size debe ser mayor que 0: %s" % batch_size)
    started = time.monotonic()
    cr = env.cr
    env.flush_all()
    updated = 0
    batches = 0
    summary = "sin respaldo de la versión anterior"

    if sql.column_exists(cr, "fleet_inspection", LEGACY_COLUMN):
        cr.execute(
            """
            SELECT vehicle_type_legacy, count(*)
              FROM fleet_inspection
             WHERE vehicle_type IS NULL AND vehicle_type_legacy NOT IN %s
             GROUP BY vehicle_type_legacy
             ORDER BY vehicle_type_legacy
            """,
            (tuple(LEGACY_XMLIDS),),
        )
        without_target = cr.fetchall()
        if without_target:
            detail = ", ".join("%s: %s" % row for row in without_target)
            raise UserError(
                env._(
                    "No se puede migrar el tipo de vehículo: hay inspecciones con valores que no tienen "
                    "destino en el catálogo (%s). La actualización se detuvo sin cambiar nada.",
                    detail,
                )
            )
        # Pares (valor viejo, id del tipo) para el VALUES del UPDATE.
        mapping = SQL(", ").join(
            SQL("(%s, %s)", legacy, env.ref(xmlid).id) for legacy, xmlid in LEGACY_XMLIDS.items()
        )
        last_id = 0
        while True:
            # Límite del lote: el id de la inspección número batch_size sin tipo después de last_id.
            cr.execute(
                """
                SELECT max(id) FROM (
                    SELECT id FROM fleet_inspection
                     WHERE id > %s AND vehicle_type IS NULL
                     ORDER BY id
                     LIMIT %s
                ) AS batch
                """,
                (last_id, batch_size),
            )
            batch_last_id = cr.fetchone()[0]
            if batch_last_id is None:
                break
            cr.execute(
                SQL(
                    """
                    UPDATE fleet_inspection AS f
                       SET vehicle_type = m.type_id
                      FROM (VALUES %s) AS m (legacy, type_id)
                     WHERE f.vehicle_type_legacy = m.legacy
                       AND f.vehicle_type IS NULL
                       AND f.id > %s AND f.id <= %s
                    """,
                    mapping,
                    last_id,
                    batch_last_id,
                )
            )
            updated += cr.rowcount
            batches += 1
            last_id = batch_last_id
            if batches % 10 == 0:
                _logger.info("Tipo de vehículo: %s lotes, %s inspecciones con tipo asignado", batches, updated)
        env["fleet.inspection"].invalidate_model(["vehicle_type"])
        cr.execute(
            """
            SELECT f.vehicle_type_legacy, t.name->>'en_US', count(*)
              FROM fleet_inspection f
              JOIN fleet_inspection_vehicle_type t ON t.id = f.vehicle_type
             WHERE f.vehicle_type_legacy IS NOT NULL
             GROUP BY 1, 2
             ORDER BY 1
            """
        )
        summary = ", ".join("%s -> %s: %s" % row for row in cr.fetchall()) or "sin inspecciones"

    # Con o sin respaldo: ninguna inspección puede quedar sin tipo.
    cr.execute("SELECT count(*) FROM fleet_inspection WHERE vehicle_type IS NULL")
    missing = cr.fetchone()[0]
    if missing:
        raise UserError(
            env._(
                "No se puede migrar el tipo de vehículo: %s inspecciones quedarían sin tipo porque no "
                "tienen un valor anterior que permita asignarlo. La actualización se detuvo sin cambiar nada.",
                missing,
            )
        )

    memory = _max_memory_mb()
    _logger.info(
        "Tipo de vehículo migrado: %s inspecciones recibieron su tipo del catálogo, en %s lotes de hasta %s, "
        "en %.2f s; memoria máxima del proceso: %s MB. Valor viejo -> tipo: %s",
        updated,
        batches,
        batch_size,
        time.monotonic() - started,
        memory if memory is not None else "no disponible",
        summary,
    )
    return updated
