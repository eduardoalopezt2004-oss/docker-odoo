from odoo import fields, models


class ShopIdempotencyKey(models.Model):
    """Clave Idempotency-Key de un POST /api/v1/orders que ya creó un pedido.

    Guarda la clave, quién la usó y un resumen (SHA-256) del cuerpo, no el cuerpo: así se sabe si
    un reintento trae el mismo contenido sin guardar los datos del cliente.
    """

    _name = "shop.idempotency.key"
    _description = "Clave de idempotencia de la API de la tienda"
    _order = "id desc"

    user_id = fields.Many2one("res.users", string="Usuario de la API", required=True, ondelete="cascade", readonly=True)
    key = fields.Char(string="Clave", required=True, readonly=True)
    request_hash = fields.Char(string="Resumen del cuerpo (SHA-256)", required=True, readonly=True)
    # Se llena en la misma transacción que reserva la clave: confirmada, la clave siempre tiene pedido.
    order_id = fields.Many2one("sale.order", string="Pedido", ondelete="cascade", readonly=True)

    _sql_constraints = [
        ("user_key_uniq", "unique(user_id, key)", "Esta clave de idempotencia ya se usó."),
    ]
