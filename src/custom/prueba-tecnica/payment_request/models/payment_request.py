from psycopg2.errors import LockNotAvailable

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import SQL

APPROVER_GROUP = "payment_request.group_payment_approver"
TREASURY_GROUP = "payment_request.group_payment_treasury"
# Código de las secuencias propias de cada compañía con código. Es distinto del contador general
# ("payment.request") para que next_by_code nunca tome una por la otra.
COMPANY_SEQUENCE_CODE = "payment.request.company"


class PaymentRequest(models.Model):
    _name = "payment.request"
    _description = "Solicitud de pago"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _check_company_auto = True
    _sql_constraints = [
        ("name_uniq", "unique(name)", "Ya existe una solicitud de pago con ese número."),
    ]

    # Se fijan al crear: si el solicitante cambiara, un aprobador podría aprobar su propia solicitud; y el
    # número lleva el código de la compañía con que se creó.
    _FIXED_FIELDS = {"name", "requester_id", "company_id"}
    # Campos que nadie puede cambiar fuera de borrador.
    _LOCKED_FIELDS = {"partner_id", "amount", "currency_id", "date", "concept"}
    # Los escribe solo el propio módulo (con sudo()): el aprobador y su fecha, el motivo del rechazo y
    # el pago. Si un usuario los pudiera escribir, podría cambiar quién aprueba o dar por pagada la solicitud.
    _SYSTEM_FIELDS = {"approver_id", "approval_date", "reject_reason", "payment_id", "payment_rate"}
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
    # Lo que se pagó, en la moneda del diario, y la tasa usada (tramo C).
    payment_currency_id = fields.Many2one(related="payment_id.currency_id", string="Moneda del pago")
    payment_amount = fields.Monetary(
        related="payment_id.amount", string="Monto pagado", currency_field="payment_currency_id"
    )
    # Sin redondeo (digits=0), como las tasas de Odoo: una tasa chica, de bolívares a dólares, perdería decimales.
    payment_rate = fields.Float(
        string="Tasa del pago",
        digits=0,
        readonly=True,
        copy=False,
        help="Unidades de la moneda del pago por cada unidad de la moneda de la solicitud, el día del pago.",
    )
    payment_rate_text = fields.Char(string="Tasa", compute="_compute_payment_rate_text")
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

    @api.depends("payment_rate", "currency_id", "payment_currency_id")
    def _compute_payment_rate_text(self):
        for request in self:
            if request.payment_currency_id and request.payment_currency_id != request.currency_id:
                request.payment_rate_text = self._format_rate(
                    request.currency_id, request.payment_currency_id, request.payment_rate
                )
            else:
                request.payment_rate_text = False

    @api.model
    def _format_rate(self, from_currency, to_currency, rate):
        """«1 USD = 40 VES»: la tasa con hasta 10 decimales, sin ceros de más ni notación científica."""
        number = ("%.10f" % rate).rstrip("0").rstrip(".")
        return "1 %s = %s %s" % (from_currency.name, number, to_currency.name)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if self._SYSTEM_FIELDS.intersection(vals) and not self.env.su:
                raise UserError(_("El aprobador, el motivo de rechazo y el pago los registra el sistema."))
            if vals.get("state", "draft") != "draft":
                raise UserError(_("Una solicitud de pago siempre se crea en borrador."))
            # El número lo pone siempre la secuencia, aunque venga otro en los valores. La compañía se fija
            # aquí, con los valores por defecto del contexto, para que el número lleve el código de la
            # compañía con que realmente se guarda.
            vals.setdefault("company_id", self.default_get(["company_id"]).get("company_id"))
            vals["name"] = self._next_request_number(self.env["res.company"].browse(vals["company_id"]))
        return super().create(vals_list)

    @api.model
    def _next_request_number(self, company):
        """Número de una solicitud nueva de ``company``.

        Sin código de compañía: contador general, SP/2026/0001, como hasta 18.0.1.1.0. Con código:
        contador propio de la compañía, DA/SP/2026/0001, que se crea con su primera solicitud.
        """
        code = company.payment_request_code
        if not code:
            return self.env["ir.sequence"].next_by_code("payment.request")
        # sudo(): quien pide el pago no puede crear secuencias; solo se usa el contador de esta compañía.
        Sequence = self.env["ir.sequence"].sudo()
        sequence = Sequence.search([("code", "=", COMPANY_SEQUENCE_CODE), ("company_id", "=", company.id)], limit=1)
        if not sequence:
            sequence = Sequence.create(
                {
                    "name": _("Solicitudes de pago de %s", company.name),
                    "code": COMPANY_SEQUENCE_CODE,
                    "company_id": company.id,
                    "prefix": "SP/%(range_year)s/",
                    "padding": 4,
                    "use_date_range": True,
                }
            )
        return "%s/%s" % (code, sequence._next())

    def write(self, vals):
        if "state" in vals:
            # Antes de validar nada: si otra persona está cambiando el estado a la vez, gana una sola.
            self._lock_for_update()
        if self._FIXED_FIELDS.intersection(vals):
            raise UserError(_("El número, el solicitante y la compañía de una solicitud no se pueden cambiar."))
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

    def _lock_for_update(self):
        """Bloquea en PostgreSQL las filas de estas solicitudes hasta que termine la transacción.

        Lo hace cada cambio de estado (enviar, aprobar, rechazar, pagar) antes de validar nada. Si otra
        persona tiene la solicitud bloqueada porque está actuando sobre ella en este momento, NOWAIT
        hace que se avise de inmediato en lugar de esperar. Después se vuelve a leer la solicitud de la
        base, para validar sobre su estado real y no sobre lo que se leyó antes del bloqueo.
        """
        if not self.ids:
            return
        try:
            with self.env.cr.savepoint(flush=False):
                # Sin registrar el error: el choque es esperado y se convierte en el aviso de abajo.
                self.env.cr.execute(
                    SQL("SELECT id FROM payment_request WHERE id IN %s FOR UPDATE NOWAIT", tuple(self.ids)),
                    log_exceptions=False,
                )
        except LockNotAvailable:
            raise UserError(
                _("Otra persona está procesando esta solicitud en este momento. Recarga la página e intenta de nuevo.")
            ) from None
        self.invalidate_recordset()

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
        self._lock_for_update()
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

    def _get_payment_terms(self, journal, payment_date):
        """Moneda, monto y tasa con que se paga esta solicitud desde ``journal`` el día ``payment_date``.

        El pago sale en la moneda del diario. Si es distinta de la de la solicitud, el monto se convierte
        con la tasa de ese día exacto. Si falta, se avisa en lugar de usar una anterior, que es lo que
        haría Odoo por defecto. También se exige cuando las dos son la misma moneda extranjera: el monto
        no cambia, pero el asiento en la moneda de la compañía se calcula con esa tasa.

        :return: (moneda del pago, monto en esa moneda, tasa: unidades de la moneda del pago por
            unidad de la moneda de la solicitud)
        :raises UserError: si falta la tasa de ese día de alguna de las dos monedas
        """
        self.ensure_one()
        company = self.company_id
        payment_date = fields.Date.to_date(payment_date)
        currency = journal.currency_id or company.currency_id
        # Las tasas de Odoo son respecto de la moneda de la compañía: esa no necesita tasa.
        for rated in (self.currency_id | currency) - company.currency_id:
            self._check_rate_of_the_day(rated, payment_date)
        if currency == self.currency_id:
            return currency, self.amount, 1.0
        rate = self.env["res.currency"]._get_conversion_rate(self.currency_id, currency, company, payment_date)
        return currency, self.currency_id._convert(self.amount, currency, company, payment_date), rate

    def _check_rate_of_the_day(self, currency, payment_date):
        """Falla si la tasa con que Odoo convertirá ``currency`` ese día no es de ese mismo día.

        Repite la búsqueda de ``res.currency._get_rates`` de Odoo 18: tasas de la compañía principal o sin
        compañía, primero las de la compañía, la más reciente hasta la fecha. Así se revisa la misma tasa
        que usará la conversión, también en una sucursal (Odoo solo deja cargar tasas en la principal).
        """
        main_company = self.company_id.root_id
        rate = self.env["res.currency.rate"].search(
            [
                ("currency_id", "=", currency.id),
                ("name", "<=", payment_date),
                ("company_id", "in", [False, main_company.id]),
            ],
            order="company_id.id, name desc",
            limit=1,
        )
        if rate.name != payment_date:
            raise UserError(
                _(
                    "No hay tasa de %(currency)s para el %(date)s en %(company)s. Pide a quien administra la "
                    "contabilidad que la cargue en Facturación → Configuración → Contabilidad → Monedas: el pago "
                    "usa la tasa de ese día, no una anterior.",
                    currency=currency.name,
                    date=payment_date.strftime("%d/%m/%Y"),
                    company=main_company.name,
                )
            )

    def _check_payment_journal(self, journal):
        """Falla si el diario no se puede usar en la compañía de la solicitud.

        Mismo criterio que Odoo 18 aplica a los diarios: los de esa compañía o los de sus compañías
        principales, así una sucursal paga desde los bancos de su principal.
        """
        self.ensure_one()
        if not journal.filtered_domain(journal._check_company_domain(self.company_id)):
            raise UserError(
                _(
                    "El diario %(journal)s es de otra compañía que la solicitud (%(company)s).",
                    journal=journal.display_name,
                    company=self.company_id.display_name,
                )
            )

    def _pay(self, journal, payment_date):
        """Registra el pago al proveedor en contabilidad y marca la solicitud como pagada.

        El pago sale en la moneda del diario, convertido con la tasa del día del pago si hace falta.
        Todo ocurre en la misma transacción: si el pago falla, la solicitud sigue aprobada. El bloqueo
        va antes de crear el pago: un doble clic o dos personas a la vez no crean dos pagos.
        """
        self.ensure_one()
        self._lock_for_update()
        self._check_state_change("paid", final=False)
        if self.payment_id:
            raise UserError(_("La solicitud %s ya tiene un pago registrado.", self.name))
        self._check_payment_journal(journal)
        currency, amount, rate = self._get_payment_terms(journal, payment_date)
        # sudo() solo para crear y publicar este pago: Tesorería no tiene permisos de Contabilidad y
        # no se los damos. Los datos del pago salen de la solicitud, no del usuario.
        payment = (
            self.env["account.payment"]
            .with_company(self.company_id)
            .sudo()
            .create(
                {
                    "payment_type": "outbound",
                    "partner_type": "supplier",
                    "partner_id": self.partner_id.id,
                    "amount": amount,
                    "currency_id": currency.id,
                    "journal_id": journal.id,
                    "date": payment_date,
                    "payment_request_id": self.id,
                }
            )
        )
        payment.action_post()
        self.sudo().write({"payment_id": payment.id, "payment_rate": rate})
        self.write({"state": "paid"})

    def _check_current_user_email(self, message):
        """Odoo necesita el correo de quien actúa para avisar a la otra persona; sin él falla con un error técnico."""
        if not self.env.user.email:
            raise UserError(message)

    def _check_current_user_email_to_reject(self):
        # Método y no función suelta: así _() encuentra el idioma del usuario en self.env.
        self._check_current_user_email(
            _(
                "Para rechazar la solicitud necesitas un correo en tu usuario: el solicitante recibe el motivo con él. "
                "Configúralo en Mi perfil o pídeselo a un administrador."
            )
        )

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
        self._check_current_user_email_to_reject()
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
