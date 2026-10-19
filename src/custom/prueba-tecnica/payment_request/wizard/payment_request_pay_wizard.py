from odoo import fields, models


class PaymentRequestPayWizard(models.TransientModel):
    _name = "payment.request.pay.wizard"
    _description = "Pago de una solicitud de pago"

    request_id = fields.Many2one("payment.request", string="Solicitud", required=True)
    partner_id = fields.Many2one(related="request_id.partner_id", string="Proveedor")
    amount = fields.Monetary(related="request_id.amount", string="Monto", currency_field="currency_id")
    currency_id = fields.Many2one(related="request_id.currency_id", string="Moneda")
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario de pago",
        required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    payment_date = fields.Date(string="Fecha del pago", required=True, default=fields.Date.context_today)

    def action_confirm(self):
        self.ensure_one()
        self.request_id._pay(self.journal_id, self.payment_date)
        return {"type": "ir.actions.act_window_close"}
