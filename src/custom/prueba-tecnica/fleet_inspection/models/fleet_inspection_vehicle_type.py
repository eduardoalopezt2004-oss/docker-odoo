from odoo import fields, models


class FleetInspectionVehicleType(models.Model):
    _name = "fleet.inspection.vehicle.type"
    _description = "Tipo de vehículo de inspección"
    _order = "name"

    name = fields.Char(string="Nombre", required=True, translate=True)
    active = fields.Boolean(default=True)
