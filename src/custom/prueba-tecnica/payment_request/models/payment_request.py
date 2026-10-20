from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

APPROVER_GROUP = "payment_request.group_payment_approver"
TREASURY_GROUP = "payment_request.group_payment_treasury"


def REJECT_EMAIL_MESSAGE():
    return _(
        "Para rechazar la solicitud necesitas un correo en tu usuario: el solicitante recibe el motivo con él. "
        "Configúralo en Mi perfil o pídeselo a un administrador."
    )


class PaymentRequest(models.Model):
    _name = "payment.request"
    _description = "Solicitud de pago"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _check_company_auto = True

    # Se fijan al crear: si el solicitante cambiara, un aprobador podría aprobar su propia solicitud.
    _FIXED_FIELDS = {"name", "requester_id"}
    # Campos que nadie puede cambiar fuera de borrador.
    _LOCKED_FIELDS = {"company_id", "partner_id", "amount", "currency_id", "date", "concept"}
    # Los escribe solo el propio módulo (con sudo()): el aprobador y su fecha, el motivo del rechazo y
    # el pago. Si un usuario los pudiera escribir, podría cambiar quién aprueba o dar por pagada la solicitud.
    _SYSTEM_FIELDS = {"approver_id", "approval_date", "reject_reason", "payment_id"}
    # Estado destino: (estados desde los que se puede llegar, grupo que hace el cambio).
    # Enviar no pide grupo: lo hace el solicitante de la solicitud.
    _TRANSITIONS = {
        "submitted": (("draft",), None),
        "approved": (("submitted",), APPROVER_GROUP),
        "rejected": (("submitted",), APPROVER_GROUP),
        "paid": (("approved",), TREASURY_GROUP),
    }

    name = fields.Char(string="Número", required=True, readonly=True, copy=False, default=lambda self: _("Nuevo"))
    company_id = fields.Many2one(
        "res.company", string="Compañía", required=True, index=True, default=lambda self: self.env.company
    )
    partner_id = fields.Many2one("res.partner", string="Proveedor", required=True, tracking=True, check_company=True)
    requester_id = fields.Many2one(
        "res.users",
        string="Solicitante",
        required=True,
        copy=False,
        default=lambda self: self.env.user,
        tracking=True,
    )
    # Sin suma al agrupar: las solicitudes pueden estar en monedas distintas.
    amount = fields.Monetary(string="Monto", required=True, currency_field="currency_id", aggregator=False, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", string="Moneda", required=True, default=lambda self: self.env.company.currency_id, tracking=True
    )
    date = fields.Date(string="Fecha", required=True, default=fields.Date.context_today)
    concept = fields.Char(string="Concepto", required=True)
    approver_id = fields.Many2one(
        "res.users", string="Aprobador", readonly=True, copy=False, tracking=True, index="btree_not_null"
    )
    approval_date = fields.Datetime(string="Fecha de aprobación", readonly=True, copy=False)
    reject_reason = fields.Text(string="Motivo del rechazo", readonly=True, copy=False)
    payment_id = fields.Many2one("account.payment", string="Pago", readonly=True, copy=False)
    # Número y fecha del pago para el formulario y el PDF. Los campos relacionados se leen como
    # superusuario: así los ve quien no tiene permisos de Contabilidad (Tesorería, el solicitante).
    payment_name = fields.Char(related="payment_id.name", string="Número del pago")
    payment_date = fields.Date(related="payment_id.date", string="Fecha del pago")
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
            if self._SYSTEM_FIELDS.intersection(vals) and not self.env.su:
                raise UserError(_("El aprobador, el motivo de rechazo y el pago los registra el sistema."))
            if vals.get("state", "draft") != "draft":
                raise UserError(_("Una solicitud de pago siempre se crea en borrador."))
            # El número lo pone siempre la secuencia, aunque venga otro en los valores.
            vals["name"] = self.env["ir.sequence"].next_by_code("payment.request")
        return super().create(vals_list)

    def write(self, vals):
        if self._FIXED_FIELDS.intersection(vals):
            raise UserError(_("El número y el solicitante de una solicitud no se pueden cambiar."))
        if self._SYSTEM_FIELDS.intersection(vals) and not self.env.su:
            raise UserError(_("El aprobador, el motivo de rechazo y el pago los registra el sistema."))
        if self._LOCKED_FIELDS.intersection(vals) and any(request.state != "draft" for request in self):
            raise UserError(_("Una solicitud enviada ya no se puede modificar."))
        if "state" in vals:
            for request in self:
                request._check_state_change(vals["state"])
        result = super().write(vals)
        if vals.get("state") == "submitted":
            self._assign_approver()
        elif vals.get("state") == "approved":
            # sudo() solo para escribir la fecha: es un campo del sistema, ningún usuario lo escribe.
            self.sudo().write({"approval_date": fields.Datetime.now()})
            self._close_approval_activity()
        elif vals.get("state") == "rejected":
            self._close_approval_activity()
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_except_not_draft(self):
        if any(request.state != "draft" for request in self):
            raise UserError(_("Solo se pueden borrar solicitudes en borrador."))

    def _check_state_change(self, new_state, final=True):
        """Valida un cambio de estado, venga de un botón, de una llamada al método o de un write directo.

        :param final: False al abrir un asistente (rechazar, pagar): ahí todavía no hay motivo ni pago.
        """
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
        if new_state == "submitted":
            if self.requester_id != user:
                raise AccessError(_("Solo quien pidió el pago puede enviar la solicitud."))
            self._get_approval_level()
        if new_state in ("approved", "rejected") and self.approver_id != user:
            raise AccessError(_("Solo el aprobador asignado a la solicitud puede aprobarla o rechazarla."))
        if new_state == "approved" and self.requester_id == user:
            raise UserError(_("No puedes aprobar tu propia solicitud. Debe aprobarla otro aprobador."))
        if final and new_state == "rejected" and not self.reject_reason:
            raise UserError(_("Una solicitud solo se rechaza con un motivo."))
        if final and new_state == "paid" and not self.payment_id:
            raise UserError(_("Una solicitud solo se marca como pagada al registrar el pago."))

    def _get_approval_level(self):
        """Nivel de aprobación que corresponde al monto, entre los de la compañía de la solicitud.

        El monto se compara en la moneda de esa compañía.

        :raises UserError: si ningún nivel cubre el monto, o si el aprobador del nivel es quien pidió el pago
        """
        self.ensure_one()
        company = self.company_id
        amount = self.currency_id._convert(self.amount, company.currency_id, company, self.date)
        level = self.env["payment.approval.level"].search(
            [("company_id", "=", company.id), ("min_amount", "<=", amount)], order="min_amount desc", limit=1
        )
        if not level:
            raise UserError(
                _(
                    "No hay un nivel de aprobación para este monto. "
                    "Pide a un administrador que configure los niveles de aprobación."
                )
            )
        if level.approver_id == self.requester_id:
            raise UserError(
                _(
                    "Esta solicitud le corresponde aprobarla a %s, que es quien la pidió. "
                    "Pide a un administrador que revise los niveles de aprobación.",
                    level.approver_id.display_name,
                )
            )
        return level

    def _assign_approver(self):
        """Fija el aprobador del nivel que corresponde y le crea una actividad para que la revise."""
        for request in self:
            approver = request._get_approval_level().approver_id
            # sudo() solo para escribir el aprobador: es un campo del sistema, ningún usuario lo escribe.
            request.sudo().write({"approver_id": approver.id})
            request.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=approver.id,
                summary=_("Aprobar solicitud de pago %s", request.name),
                note=_(
                    "%(requester)s pidió un pago de %(amount)s %(currency)s para %(partner)s.",
                    requester=request.requester_id.name,
                    amount=request.amount,
                    currency=request.currency_id.name,
                    partner=request.partner_id.name,
                ),
            )

    def _close_approval_activity(self):
        # Se borra la actividad en lugar de marcarla hecha: así el chatter no suma un mensaje aparte
        # del cambio de estado.
        self.activity_unlink(["mail.mail_activity_data_todo"])

    def _reject(self, reason):
        """Rechaza la solicitud con el motivo, que queda en el campo y en el chatter."""
        self.ensure_one()
        # El motivo se escribe antes porque el cambio de estado exige que exista.
        self._check_state_change("rejected", final=False)
        # sudo() solo para escribir el motivo: es un campo del sistema, ningún usuario lo escribe.
        self.sudo().write({"reject_reason": reason})
        # Mensaje y no nota: así el solicitante recibe el aviso con el motivo.
        self.message_post(
            body=_("Solicitud rechazada. Motivo: %s", reason),
            subtype_xmlid="mail.mt_comment",
            partner_ids=self.requester_id.partner_id.ids,
        )
        self.write({"state": "rejected"})

    def _pay(self, journal, payment_date):
        """Registra el pago al proveedor en contabilidad y marca la solicitud como pagada.

        Todo ocurre en la misma transacción: si el pago falla, la solicitud sigue aprobada.
        """
        self.ensure_one()
        self._check_state_change("paid", final=False)
        if self.payment_id:
            raise UserError(_("La solicitud %s ya tiene un pago registrado.", self.name))
        # sudo() solo para crear y publicar este pago: Tesorería no tiene permisos de Contabilidad y
        # no se los damos. Los datos del pago salen de la solicitud, no del usuario.
        payment = (
            self.env["account.payment"]
            .sudo()
            .create(
                {
                    "payment_type": "outbound",
                    "partner_type": "supplier",
                    "partner_id": self.partner_id.id,
                    "amount": self.amount,
                    "currency_id": self.currency_id.id,
                    "journal_id": journal.id,
                    "date": payment_date,
                    "payment_request_id": self.id,
                }
            )
        )
        payment.action_post()
        self.sudo().write({"payment_id": payment.id})
        self.write({"state": "paid"})

    def _check_current_user_email(self, message):
        """Odoo necesita el correo de quien actúa para avisar a la otra persona; sin él falla con un error técnico."""
        if not self.env.user.email:
            raise UserError(message)

    def action_submit(self):
        self._check_current_user_email(
            _(
                "Para enviar la solicitud necesitas un correo en tu usuario: el aprobador recibe el aviso con él. "
                "Configúralo en Mi perfil o pídeselo a un administrador."
            )
        )
        self.write({"state": "submitted"})

    def action_approve(self):
        self.write({"state": "approved"})

    def action_reject(self):
        """Abre el asistente del motivo; el rechazo lo hace el asistente."""
        self.ensure_one()
        self._check_state_change("rejected", final=False)
        self._check_current_user_email(REJECT_EMAIL_MESSAGE())
        return {
            "type": "ir.actions.act_window",
            "name": _("Rechazar solicitud"),
            "res_model": "payment.request.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id},
        }

    def action_mark_paid(self):
        """Abre el asistente del pago; el pago y el cambio de estado los hace el asistente."""
        self.ensure_one()
        self._check_state_change("paid", final=False)
        return {
            "type": "ir.actions.act_window",
            "name": _("Pagar solicitud"),
            "res_model": "payment.request.pay.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id},
        }

    def action_view_payment(self):
        self.ensure_one()
        if not self.payment_id:
            raise UserError(_("Esta solicitud todavía no tiene un pago registrado."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Pago"),
            "res_model": "account.payment",
            "view_mode": "form",
            "res_id": self.payment_id.id,
        }
