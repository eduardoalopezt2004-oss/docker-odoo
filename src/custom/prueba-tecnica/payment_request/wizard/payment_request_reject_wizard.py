from odoo import _, fields, models
from odoo.exceptions import ValidationError


class PaymentRequestRejectWizard(models.TransientModel):
    _name = "payment.request.reject.wizard"
    _description = "Rechazo de una solicitud de pago"

    request_id = fields.Many2one("payment.request", string="Solicitud", required=True)
    reason = fields.Text(string="Motivo del rechazo", required=True)

    def action_confirm(self):
        self.ensure_one()
        self.request_id._check_current_user_email_to_reject()
        reason = (self.reason or "").strip()
        if not reason:
            raise ValidationError(_("Indica el motivo del rechazo: el solicitante necesita saber por qué."))
        self.request_id._reject(reason)
        return {"type": "ir.actions.act_window_close"}
