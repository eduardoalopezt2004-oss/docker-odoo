from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    commission_percent = fields.Float(
        string="Comisión (%)",
        digits=(5, 2),
        readonly=True,
        copy=False,
        help="Se fija al confirmar el pedido, para que la comisión no cambie si después se modifican los porcentajes.",
    )
    commission_amount = fields.Monetary(
        string="Comisión",
        compute="_compute_commission_amount",
        store=True,
    )

    @api.depends("commission_percent", "price_subtotal")
    def _compute_commission_amount(self):
        for line in self:
            line.commission_amount = line.price_subtotal * line.commission_percent / 100.0

    def _get_commission_percent(self):
        """Porcentaje de la categoría del producto (la más específica) o, si no hay, el del vendedor."""
        self.ensure_one()
        # sudo(): quien confirma puede ser un vendedor, que no tiene acceso a las reglas (son
        # configuración del gerente). La búsqueda se limita a la categoría del producto y a su
        # compañía, y solo se usa el porcentaje. El modelo no tiene reglas de registro que saltar.
        rules = self.env["sale.commission.rule"].sudo().search([
            ("categ_id", "parent_of", self.product_id.categ_id.id),
            ("company_id", "in", [False, self.company_id.id]),
        ])
        if rules:
            return rules.sorted(lambda r: len(r.categ_id.parent_path or ""), reverse=True)[0].percent
        return self.env.user.commission_percent
