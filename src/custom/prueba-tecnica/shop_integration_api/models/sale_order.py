from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Solo los pedidos con esta marca avisan a la tienda al validar su entrega.
    shop_api_order = fields.Boolean(string="Creado por la API de la tienda", readonly=True, copy=False)

    def _shop_fully_delivered(self):
        """True si ya no queda nada por entregar: ninguna entrega al cliente sin validar ni cancelar.

        También es True cuando lo que falta se canceló (validar una entrega parcial sin entrega
        pendiente): así la tienda sabe que no llegará otro aviso. Los servicios no generan entregas.
        """
        self.ensure_one()
        pending = self.picking_ids.filtered(
            lambda picking: picking.picking_type_code == "outgoing" and picking.state not in ("done", "cancel")
        )
        return not pending
