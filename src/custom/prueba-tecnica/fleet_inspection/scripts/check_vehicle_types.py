"""Cuenta las inspecciones por tipo de vehículo. SOLO LECTURA: no escribe en la base.

Sirve antes y después de actualizar a 18.0.1.1.0 (ver MIGRATION_PLAN.md):

- En 18.0.1.0.0 cuenta por el valor de la selección (`car`, `truck`…).
- En 18.0.1.1.0 cuenta por valor viejo y tipo del catálogo, y las inspecciones sin tipo,
  que deben ser 0.

Uso, desde la raíz del repositorio:

    docker compose -f docker-compose.generated.yml exec -T odoo-prueba-tecnica \\
        odoo shell -d <base> --no-http < src/custom/prueba-tecnica/fleet_inspection/scripts/check_vehicle_types.py

Al final deshace la transacción por si acaso: este script no debe cambiar nada.
"""
# pylint: disable=print-used
# Script de operador para odoo shell: lo que imprime es el informe para quien lo corre.
from odoo.tools import sql


def rows(cr, query):
    cr.execute(query)
    return cr.fetchall()


def main(env):
    cr = env.cr
    version = rows(cr, "SELECT latest_version FROM ir_module_module WHERE name = 'fleet_inspection'")
    print("Versión instalada de fleet_inspection:", version[0][0] if version else "no instalado")
    print("Total de inspecciones:", rows(cr, "SELECT count(*) FROM fleet_inspection")[0][0])

    vehicle_type = sql.table_columns(cr, "fleet_inspection").get("vehicle_type")
    if vehicle_type and vehicle_type["udt_name"] in ("varchar", "text"):
        print("Formato: 18.0.1.0.0 (selección)")
        print("Por tipo (selección):")
        for value, count in rows(cr, "SELECT vehicle_type, count(*) FROM fleet_inspection GROUP BY 1 ORDER BY 1"):
            print(f"  {value}: {count}")
        return

    print("Formato: 18.0.1.1.0 (catálogo)")
    if sql.column_exists(cr, "fleet_inspection", "vehicle_type_legacy"):
        print("Por valor viejo -> tipo del catálogo:")
        for legacy, type_name, count in rows(
            cr,
            """
            SELECT f.vehicle_type_legacy, t.name->>'en_US', count(*)
              FROM fleet_inspection f
              LEFT JOIN fleet_inspection_vehicle_type t ON t.id = f.vehicle_type
             GROUP BY 1, 2 ORDER BY 1, 2
            """,
        ):
            print(f"  {legacy} -> {type_name}: {count}")
    else:
        print("Sin columna vehicle_type_legacy: la base se instaló directamente en 18.0.1.1.0.")
    print("Inspecciones sin tipo (debe ser 0):", rows(cr, "SELECT count(*) FROM fleet_inspection WHERE vehicle_type IS NULL")[0][0])


try:
    main(env)  # noqa: F821  (env lo define odoo shell)
finally:
    env.cr.rollback()  # noqa: F821
