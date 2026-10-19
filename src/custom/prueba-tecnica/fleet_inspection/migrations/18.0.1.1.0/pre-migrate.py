from odoo.addons.fleet_inspection.tools.vehicle_type_migration import preserve_legacy_vehicle_type


def migrate(cr, version):
    # Guarda el tipo de cada inspección en vehicle_type_legacy antes de que el
    # ORM convierta vehicle_type en many2one.
    if not version:
        return
    preserve_legacy_vehicle_type(cr)
