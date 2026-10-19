from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

APPROVER_GROUP = "payment_request.group_payment_approver"


class PaymentApprovalLevel(models.Model):
    """Nivel de aprobación: desde este monto mínimo, la solicitud la aprueba este usuario.

    Se elige el nivel con el mayor monto mínimo que no supere el monto de la solicitud,
    medido en la moneda de la compañía.
    """

    _name = "payment.approval.level"
    _description = "Nivel de aprobación de pagos"
    _order = "min_amount, id"

    name = fields.Char(string="Nombre", required=True)
    company_id = fields.Many2one("res.company", string="Compañía", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id", string="Moneda")
    min_amount = fields.Monetary(string="Monto mínimo", required=True, currency_field="currency_id", default=0.0)
    approver_id = fields.Many2one(
        "res.users",
        string="Aprobador",
        required=True,
        domain=lambda self: [("groups_id", "in", self.env.ref(APPROVER_GROUP).ids)],
    )

    _sql_constraints = [
        (
            "company_min_amount_uniq",
            "unique(company_id, min_amount)",
            "Ya hay un nivel de aprobación con ese monto mínimo en esta compañía.",
        ),
    ]

    @api.constrains("min_amount")
    def _check_min_amount(self):
        for level in self:
            if level.currency_id.compare_amounts(level.min_amount, 0.0) < 0:
                raise ValidationError(_("El monto mínimo de un nivel no puede ser negativo."))

    @api.constrains("approver_id")
    def _check_approver_group(self):
        for level in self:
            if not level.approver_id.has_group(APPROVER_GROUP):
                raise ValidationError(
                    _("%s no tiene el grupo Aprobador de solicitudes de pago.", level.approver_id.display_name)
                )
