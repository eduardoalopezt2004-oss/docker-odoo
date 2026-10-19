from odoo import fields, models


class ShopApiLog(models.Model):
    """Una fila por llamada a la API de la tienda.

    No guarda cabeceras, cuerpo, consulta ni IP: así la clave y los datos del
    cliente no tienen por dónde llegar al log.
    """

    _name = "shop.api.log"
    _description = "Registro de llamadas a la API de la tienda"
    _order = "id desc"

    endpoint = fields.Char(string="Endpoint", required=True, readonly=True)
    user_id = fields.Many2one("res.users", string="Usuario", readonly=True, ondelete="set null", index=True)
    status_code = fields.Integer(string="Código HTTP", required=True, readonly=True)
    duration_ms = fields.Integer(string="Duración (ms)", readonly=True)
    error_code = fields.Char(string="Código de error", readonly=True)
