from odoo import fields, models
from odoo.tools import float_compare


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Solo los pedidos con esta marca avisan a la tienda al validar su entrega.
    shop_api_order = fields.Boolean(string="Creado por la API de la tienda", readonly=True, copy=False)

    def _shop_fully_delivered(self):
        """True si ya se entregó todo lo que sale del almacén (servicios y notas no cuentan)."""
        self.ensure_one()
        lines = self.order_line.filtered(lambda line: line.qty_delivered_method == "stock_move")
        return all(
            float_compare(line.qty_delivered, line.product_uom_qty, precision_rounding=line.product_uom.rounding) >= 0
            for line in lines
        )
