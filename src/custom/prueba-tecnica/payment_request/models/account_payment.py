from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    payment_request_id = fields.Many2one(
        "payment.request", string="Solicitud de pago", readonly=True, copy=False, index="btree_not_null"
    )
