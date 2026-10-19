from odoo import SUPERUSER_ID, api

from odoo.addons.fleet_inspection.tools.vehicle_type_migration import map_legacy_vehicle_types


def migrate(cr, version):
    # El catálogo ya está cargado: asigna a cada inspección su tipo según el
    # valor guardado en vehicle_type_legacy.
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    map_legacy_vehicle_types(env)
