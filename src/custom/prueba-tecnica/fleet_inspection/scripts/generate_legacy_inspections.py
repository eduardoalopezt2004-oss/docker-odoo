"""Genera inspecciones de prueba en la versión 18.0.1.0.0 (tipo de vehículo como selección).

Es la base del ensayo del tramo C: muchas inspecciones en la versión anterior, para medir
cuánto tarda la actualización a 18.0.1.1.0 y comprobar que la migración se puede repetir.

SOLO PARA BASES DE PRUEBA: crea vehículos e inspecciones y confirma la transacción cada
lote. Se niega a correr si el tipo de vehículo ya es el catálogo de 18.0.1.1.0.

Uso, desde la raíz del repositorio y con el código de 18.0.1.0.0 (ver MIGRATION_PLAN.md):

    docker compose -f docker-compose.generated.yml exec -T odoo-prueba-tecnica \\
        odoo shell -d <base> --no-http < /tmp/generate_legacy_inspections.py

Variables de entorno (se pasan con `exec -T -e NOMBRE=valor`):

- FLEET_GEN_COUNT: inspecciones a crear (10000).
- FLEET_GEN_BATCH: inspecciones por lote; se confirma la transacción y se vacía la caché
  después de cada uno, para que la memoria no crezca (500).
- FLEET_GEN_SEED: semilla del azar; con la misma semilla salen los mismos datos (42).
- FLEET_GEN_VEHICLES: vehículos de prueba entre los que se reparten (50).

Reparto: tipo moto 30 %, carro 40 %, camión 20 %, otro 10 %; estado borrador 25 %,
en curso 25 %, aprobada 35 %, rechazada 15 %; fecha en el último año. Cada inspección
lleva el checklist completo, como al crearla desde el formulario. El chatter no registra
la creación ni los cambios de estado, para no medir el correo en lugar de los datos.
"""
# pylint: disable=print-used
# Script de operador para odoo shell: lo que imprime es el informe para quien lo corre.
import os
import random
import time
from datetime import timedelta

from odoo import fields

try:
    import resource
except ImportError:
    resource = None

COUNT = int(os.environ.get("FLEET_GEN_COUNT", "10000"))
BATCH = int(os.environ.get("FLEET_GEN_BATCH", "500"))
SEED = int(os.environ.get("FLEET_GEN_SEED", "42"))
VEHICLES = int(os.environ.get("FLEET_GEN_VEHICLES", "50"))

TYPE_WEIGHTS = {"motorcycle": 30, "car": 40, "truck": 20, "other": 10}
STATE_WEIGHTS = {"draft": 25, "in_progress": 25, "approved": 35, "rejected": 15}
PLATE_PREFIX = "ENS-"
QUIET = {
    "tracking_disable": True,
    "mail_create_nolog": True,
    "mail_create_nosubscribe": True,
    "mail_notrack": True,
}


def max_memory_mb():
    if resource is None:
        return "no disponible"
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)


def get_vehicles(env, count):
    """Vehículos ENS-0001…; reutiliza los que ya existan de una corrida anterior."""
    Vehicle = env["fleet.vehicle"]
    existing = Vehicle.search([("license_plate", "=like", PLATE_PREFIX + "%")])
    missing = count - len(existing)
    if missing > 0:
        brand = env["fleet.vehicle.model.brand"].create({"name": "Marca de ensayo"})
        model = env["fleet.vehicle.model"].create({"name": "Modelo de ensayo", "brand_id": brand.id})
        start = len(existing) + 1
        existing |= Vehicle.create(
            [
                {"model_id": model.id, "license_plate": "%s%04d" % (PLATE_PREFIX, number)}
                for number in range(start, start + missing)
            ]
        )
    return existing.ids[:count]


def main(env):
    Inspection = env["fleet.inspection"].with_context(**QUIET)
    if Inspection._fields["vehicle_type"].type != "selection":
        raise SystemExit(
            "El tipo de vehículo ya es el catálogo de 18.0.1.1.0. Este script crea datos de la versión "
            "18.0.1.0.0: corre la base con ese código (ver MIGRATION_PLAN.md)."
        )
    if COUNT < 1 or BATCH < 1 or VEHICLES < 1:
        raise SystemExit("FLEET_GEN_COUNT, FLEET_GEN_BATCH y FLEET_GEN_VEHICLES deben ser mayores que 0.")

    rng = random.Random(SEED)
    started = time.monotonic()
    vehicle_ids = get_vehicles(env, VEHICLES)
    inspector_id = env.ref("base.user_admin").id
    today = fields.Date.context_today(Inspection)
    env.cr.commit()
    print(f"Generando {COUNT} inspecciones en lotes de {BATCH} (semilla {SEED}, {len(vehicle_ids)} vehículos)")

    created = 0
    while created < COUNT:
        size = min(BATCH, COUNT - created)
        states = rng.choices(list(STATE_WEIGHTS), weights=list(STATE_WEIGHTS.values()), k=size)
        vals_list = [
            {
                "vehicle_id": rng.choice(vehicle_ids),
                "vehicle_type": rng.choices(list(TYPE_WEIGHTS), weights=list(TYPE_WEIGHTS.values()))[0],
                "inspector_id": inspector_id,
                "date": today - timedelta(days=rng.randint(0, 365)),
                "odometer": rng.randint(0, 300000),
            }
            for _ in range(size)
        ]
        inspections = Inspection.create(vals_list)
        for state in STATE_WEIGHTS:
            if state == "draft":
                continue
            group = inspections.browse(
                [inspection.id for inspection, wanted in zip(inspections, states) if wanted == state]
            )
            if group:
                group.write({"state": state})
        env.cr.commit()
        env.invalidate_all()
        created += size
        print(f"  {created} / {COUNT} en {time.monotonic() - started:.1f} s")

    elapsed = time.monotonic() - started
    print(f"\nListo: {created} inspecciones en {elapsed:.1f} s ({created / elapsed:.0f} por segundo)")
    print(f"Memoria máxima del proceso: {max_memory_mb()} MB")
    env.cr.execute("SELECT vehicle_type, count(*) FROM fleet_inspection GROUP BY 1 ORDER BY 1")
    print("Inspecciones en la base por tipo:", ", ".join("%s: %s" % row for row in env.cr.fetchall()))
    env.cr.execute("SELECT state, count(*) FROM fleet_inspection GROUP BY 1 ORDER BY 1")
    print("Inspecciones en la base por estado:", ", ".join("%s: %s" % row for row in env.cr.fetchall()))
    env.cr.execute("SELECT count(*) FROM fleet_inspection_line")
    print("Líneas de checklist en la base:", env.cr.fetchone()[0])


main(env)  # noqa: F821  (env lo define odoo shell)
