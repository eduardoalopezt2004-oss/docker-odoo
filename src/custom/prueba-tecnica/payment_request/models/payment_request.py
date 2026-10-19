from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

APPROVER_GROUP = "payment_request.group_payment_approver"
TREASURY_GROUP = "payment_request.group_payment_treasury"


class PaymentRequest(models.Model):
    _name = "payment.request"
    _description = "Solicitud de pago"
    _inherit = ["mail.thread"]
    _order = "id desc"

    # Campos que nadie puede cambiar fuera de borrador.
    _LOCKED_FIELDS = {"name", "partner_id", "requester_id", "amount", "currency_id", "date", "concept"}
    # Estado destino: (estados desde los que se puede llegar, grupo que hace el cambio).
    # Enviar no pide grupo: lo hace el solicitante de la solicitud.
    _TRANSITIONS = {
        "submitted": (("draft",), None),
        "approved": (("submitted",), APPROVER_GROUP),
        "rejected": (("submitted",), APPROVER_GROUP),
        "paid": (("approved",), TREASURY_GROUP),
    }

    name = fields.Char(string="Número", required=True, readonly=True, copy=False, default=lambda self: _("Nuevo"))
    partner_id = fields.Many2one("res.partner", string="Proveedor", required=True, tracking=True)
    requester_id = fields.Many2one(
        "res.users", string="Solicitante", required=True, default=lambda self: self.env.user, tracking=True
    )
    # Sin suma al agrupar: las solicitudes pueden estar en monedas distintas.
    amount = fields.Monetary(string="Monto", required=True, currency_field="currency_id", aggregator=False, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", string="Moneda", required=True, default=lambda self: self.env.company.currency_id, tracking=True
    )
    date = fields.Date(string="Fecha", required=True, default=fields.Date.context_today)
    concept = fields.Char(string="Concepto", required=True)
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("submitted", "Enviada"),
            ("approved", "Aprobada"),
            ("paid", "Pagada"),
            ("rejected", "Rechazada"),
        ],
        string="Estado",
        required=True,
        readonly=True,
        copy=False,
        default="draft",
        index=True,
        tracking=True,
    )

    @api.constrains("amount", "currency_id")
    def _check_amount_positive(self):
        for request in self:
            if request.currency_id.compare_amounts(request.amount, 0.0) <= 0:
                raise ValidationError(_("El monto de la solicitud debe ser mayor que cero."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("state", "draft") != "draft":
                raise UserError(_("Una solicitud de pago siempre se crea en borrador."))
            # El número lo pone siempre la secuencia, aunque venga otro en los valores.
            vals["name"] = self.env["ir.sequence"].next_by_code("payment.request")
        return super().create(vals_list)

    def write(self, vals):
        if self._LOCKED_FIELDS.intersection(vals) and any(request.state != "draft" for request in self):
            raise UserError(_("Una solicitud enviada ya no se puede modificar."))
        if "state" in vals:
            for request in self:
                request._check_state_change(vals["state"])
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_not_draft(self):
        if any(request.state != "draft" for request in self):
            raise UserError(_("Solo se pueden borrar solicitudes en borrador."))

    def _check_state_change(self, new_state):
        """Valida un cambio de estado, venga de un botón, de una llamada al método o de un write directo."""
        self.ensure_one()
        if new_state not in self._TRANSITIONS:
            raise UserError(_("Una solicitud de pago no puede volver a borrador."))
        from_states, group = self._TRANSITIONS[new_state]
        user = self.env.user
        if group == APPROVER_GROUP and not user.has_group(group):
            raise AccessError(_("Solo un aprobador puede aprobar o rechazar solicitudes de pago."))
        if group == TREASURY_GROUP and not user.has_group(group):
            raise AccessError(_("Solo Tesorería puede marcar una solicitud como pagada."))
        if self.state not in from_states:
            labels = dict(self._fields["state"]._description_selection(self.env))
            raise UserError(
                _(
                    "La solicitud %(name)s está %(state)s y no se puede pasar a %(new_state)s.",
                    name=self.name,
                    state=labels[self.state].lower(),
                    new_state=labels[new_state].lower(),
                )
            )
        if new_state == "submitted" and self.requester_id != user:
            raise AccessError(_("Solo quien pidió el pago puede enviar la solicitud."))
        if new_state == "approved" and self.requester_id == user:
            raise UserError(_("No puedes aprobar tu propia solicitud. Debe aprobarla otro aprobador."))

    def action_submit(self):
        self.write({"state": "submitted"})

    def action_approve(self):
        self.write({"state": "approved"})

    def action_reject(self):
        self.write({"state": "rejected"})

    def action_mark_paid(self):
        self.write({"state": "paid"})
