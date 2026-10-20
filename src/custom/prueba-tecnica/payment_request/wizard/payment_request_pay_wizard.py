from odoo import api, fields, models
from odoo.exceptions import UserError


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
        # parent_of: una sucursal también paga desde los bancos de su compañía principal, como en Odoo.
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', 'parent_of', company_id)]",
    )
    company_id = fields.Many2one(related="request_id.company_id")
    payment_date = fields.Date(string="Fecha del pago", required=True, default=fields.Date.context_today)
    # Vista previa antes de confirmar (tramo C): lo que se va a pagar y con qué tasa.
    payment_currency_id = fields.Many2one(
        "res.currency", string="Moneda del pago", compute="_compute_payment_preview"
    )
    payment_amount = fields.Monetary(
        string="Monto a pagar", currency_field="payment_currency_id", compute="_compute_payment_preview"
    )
    rate = fields.Float(string="Tasa", digits=(16, 6), compute="_compute_payment_preview")
    rate_text = fields.Char(string="Tasa del día", compute="_compute_payment_preview")
    rate_warning = fields.Char(compute="_compute_payment_preview")

    @api.depends("request_id", "journal_id", "payment_date")
    def _compute_payment_preview(self):
        for wizard in self:
            wizard.payment_currency_id = wizard.journal_id.currency_id or wizard.company_id.currency_id
            wizard.payment_amount = 0.0
            wizard.rate = 0.0
            wizard.rate_text = False
            wizard.rate_warning = False
            if not (wizard.request_id and wizard.journal_id and wizard.payment_date):
                continue
            try:
                currency, amount, rate = wizard.request_id._get_payment_terms(wizard.journal_id, wizard.payment_date)
            except UserError as error:
                wizard.rate_warning = error.args[0]
                continue
            wizard.payment_currency_id = currency
            wizard.payment_amount = amount
            wizard.rate = rate
            if currency != wizard.request_id.currency_id:
                wizard.rate_text = "1 %s = %s %s (tasa del %s)" % (
                    wizard.request_id.currency_id.name,
                    "%.10g" % rate,
                    currency.name,
                    wizard.payment_date.strftime("%d/%m/%Y"),
                )

    def action_confirm(self):
        self.ensure_one()
        self.request_id._pay(self.journal_id, self.payment_date)
        return {"type": "ir.actions.act_window_close"}
