from lxml import etree

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPaymentRequest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Proveedor de prueba"})
        group_user = cls.env.ref("base.group_user")
        # El solicitante solo tiene el grupo de usuario interno: así se prueba que cualquier empleado puede pedir pagos.
        cls.requester = cls._create_user("solicitante_test", group_user)
        cls.other_requester = cls._create_user("otro_solicitante_test", group_user)
        cls.approver = cls._create_user(
            "aprobador_test", group_user | cls.env.ref("payment_request.group_payment_approver")
        )
        cls.treasurer = cls._create_user(
            "tesoreria_test", group_user | cls.env.ref("payment_request.group_payment_treasury")
        )
        # Desde el tramo B el aprobador sale del nivel que corresponde al monto: un nivel general.
        cls.env["payment.approval.level"].create(
            {"name": "General", "min_amount": 0.0, "approver_id": cls.approver.id}
        )
        cls.journal = cls._bank_journal()

    @classmethod
    def _create_user(cls, login, groups):
        return (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create({"name": login, "login": login, "email": f"{login}@example.com", "groups_id": [Command.set(groups.ids)]})
        )

    @classmethod
    def _bank_journal(cls):
        company = cls.env.company
        journal = cls.env["account.journal"].search([("type", "=", "bank"), ("company_id", "=", company.id)], limit=1)
        return journal or cls.env["account.journal"].create(
            {"name": "Banco de prueba", "type": "bank", "code": "PRBK", "company_id": company.id}
        )

    def _pay(self, request, user=None):
        wizard = (
            self.env["payment.request.pay.wizard"]
            .with_user(user or self.treasurer)
            .create({"request_id": request.id, "journal_id": self.journal.id})
        )
        return wizard.action_confirm()

    def _reject(self, request, user=None, reason="Falta la factura"):
        wizard = (
            self.env["payment.request.reject.wizard"]
            .with_user(user or self.approver)
            .create({"request_id": request.id, "reason": reason})
        )
        return wizard.action_confirm()

    def _new_request(self, user=None, **vals):
        values = {"partner_id": self.partner.id, "amount": 150.0, "concept": "Compra de repuestos"}
        values.update(vals)
        return self.env["payment.request"].with_user(user or self.requester).create(values)

    def _submitted_request(self, user=None):
        request = self._new_request(user)
        request.action_submit()
        return request

    def _flush_tracking(self):
        self.env.flush_all()
        self.env.cr.precommit.run()

    # Datos al crear

    def test_internal_user_is_requester(self):
        self.assertTrue(self.requester.has_group("payment_request.group_payment_requester"))

    def test_create_defaults_and_sequence(self):
        request = self._new_request()
        self.assertRegex(request.name, r"^SP/%s/\d{4}$" % fields.Date.today().year)
        self.assertEqual(request.requester_id, self.requester)
        self.assertEqual(request.currency_id, self.env.company.currency_id)
        self.assertEqual(request.date, fields.Date.context_today(request))
        self.assertEqual(request.state, "draft")
        following = self._new_request()
        self.assertEqual(int(following.name[-4:]), int(request.name[-4:]) + 1)

    def test_amount_must_be_positive(self):
        for amount in (0.0, -10.0):
            with self.assertRaises(ValidationError):
                self._new_request(amount=amount)
        request = self._new_request()
        with self.assertRaises(ValidationError):
            request.write({"amount": 0.0})

    def test_cannot_create_in_other_state(self):
        with self.assertRaises(UserError):
            self._new_request(state="approved")

    def test_cannot_create_for_another_user(self):
        with self.assertRaises(AccessError):
            self._new_request(requester_id=self.other_requester.id)

    def test_number_and_requester_fixed_after_create(self):
        request = self._new_request()
        with self.assertRaises(UserError):
            request.write({"requester_id": self.other_requester.id})
        with self.assertRaises(UserError):
            request.write({"name": "SP/2026/0001"})
        # Un aprobador no puede pasar su solicitud a otro al enviarla para luego aprobarla.
        own = self._new_request(self.approver)
        with self.assertRaises(UserError):
            own.write({"state": "submitted", "requester_id": self.requester.id})
        self.assertEqual(own.state, "draft")
        self.assertEqual(own.requester_id, self.approver)

    def test_copy_belongs_to_current_user(self):
        request = self._submitted_request()
        copy = request.with_user(self.approver).copy()
        self.assertEqual(copy.requester_id, self.approver)
        self.assertEqual(copy.state, "draft")
        self.assertNotEqual(copy.name, request.name)

    # Flujo

    def test_full_flow(self):
        request = self._new_request()
        request.action_submit()
        self.assertEqual(request.state, "submitted")
        request.with_user(self.approver).action_approve()
        self.assertEqual(request.state, "approved")
        self._pay(request)
        self.assertEqual(request.state, "paid")

    def test_state_changes_logged_in_chatter(self):
        request = self._new_request()
        self._flush_tracking()
        steps = [
            (request.action_submit, self.requester),
            (request.with_user(self.approver).action_approve, self.approver),
            (lambda: self._pay(request), self.treasurer),
        ]
        for action, user in steps:
            action()
            self._flush_tracking()
            # sudo() solo para leer: en Odoo 18 los valores de seguimiento son de acceso restringido.
            last_message = request.sudo().message_ids[0]
            state_tracking = last_message.tracking_value_ids.filtered(lambda t: t.field_id.name == "state")
            self.assertTrue(state_tracking)
            self.assertEqual(last_message.author_id, user.partner_id)

    def test_rejected_is_final(self):
        request = self._submitted_request()
        self._reject(request)
        self.assertEqual(request.state, "rejected")
        with self.assertRaises(UserError):
            request.action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.approver).action_approve()
        with self.assertRaises(UserError):
            request.with_user(self.treasurer).action_mark_paid()
        self.assertEqual(request.state, "rejected")

    def test_wrong_order_and_double_execution(self):
        request = self._new_request()
        with self.assertRaises(UserError):
            request.with_user(self.approver).action_approve()
        request.action_submit()
        with self.assertRaises(UserError):
            request.action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.treasurer).action_mark_paid()
        request.with_user(self.approver).action_approve()
        with self.assertRaises(UserError):
            request.with_user(self.approver).action_approve()
        self._pay(request)
        with self.assertRaises(UserError):
            request.with_user(self.treasurer).action_mark_paid()
        self.assertEqual(request.state, "paid")

    def test_no_way_back_to_draft(self):
        request = self._submitted_request()
        for user in (self.requester, self.approver):
            with self.assertRaises(UserError):
                request.with_user(user).write({"state": "draft"})

    # Lo que cada grupo no puede hacer

    def test_requester_sees_only_own(self):
        own = self._new_request()
        other = self._new_request(self.other_requester)
        found = self.env["payment.request"].with_user(self.requester).search([])
        self.assertIn(own, found)
        self.assertNotIn(other, found)
        with self.assertRaises(AccessError):
            other.with_user(self.requester).read(["amount"])
        found = self.env["payment.request"].with_user(self.approver).search([])
        self.assertIn(own, found)
        self.assertIn(other, found)

    def test_requester_cannot_approve_reject_or_pay(self):
        request = self._submitted_request()
        for method in ("action_approve", "action_reject", "action_mark_paid"):
            with self.assertRaises(AccessError):
                getattr(request, method)()
        for state in ("approved", "rejected", "paid"):
            with self.assertRaises(AccessError):
                request.write({"state": state})
        self.assertEqual(request.state, "submitted")

    def test_approver_cannot_approve_own_request(self):
        # El envío ya falla si el aprobador del nivel es quien pidió el pago...
        request = self._new_request(self.approver)
        with self.assertRaises(UserError):
            request.action_submit()
        self.assertEqual(request.state, "draft")
        # ...y aunque la solicitud llegara a enviada por otro camino (aquí, por SQL), no la aprueba.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE payment_request SET state = 'submitted', approver_id = %s WHERE id = %s",
            (self.approver.id, request.id),
        )
        self.env.invalidate_all()
        with self.assertRaises(UserError):
            request.action_approve()
        self.assertEqual(request.state, "submitted")

    def test_treasury_cannot_approve_and_approver_cannot_pay(self):
        request = self._submitted_request()
        with self.assertRaises(AccessError):
            request.with_user(self.treasurer).action_approve()
        request.with_user(self.approver).action_approve()
        with self.assertRaises(AccessError):
            request.with_user(self.approver).action_mark_paid()
        self.assertEqual(request.state, "approved")

    def test_only_owner_submits(self):
        request = self._new_request()
        with self.assertRaises(AccessError):
            request.with_user(self.approver).action_submit()
        self.assertEqual(request.state, "draft")

    def test_submitted_request_not_editable(self):
        request = self._new_request()
        request.write({"amount": 200.0})
        request.action_submit()
        for user in (self.requester, self.approver):
            with self.assertRaises(UserError):
                request.with_user(user).write({"amount": 999.0})
        # Tampoco con sudo(): la regla es del modelo, no de los permisos.
        with self.assertRaises(UserError):
            request.sudo().write({"concept": "Otro concepto"})
        self.assertEqual(request.amount, 200.0)

    def test_unlink_only_draft(self):
        submitted = self._submitted_request()
        with self.assertRaises(UserError):
            submitted.unlink()
        draft = self._new_request()
        draft.unlink()
        self.assertFalse(draft.exists())

    # Botones según grupo y estado

    def _form_buttons(self, user):
        arch = self.env["payment.request"].with_user(user).get_views([(False, "form")])["views"]["form"]["arch"]
        # Solo los botones de método: el de imprimir es una acción de informe.
        return {
            button.get("name"): button.get("invisible")
            for button in etree.fromstring(arch).iter("button")
            if button.get("type") == "object"
        }

    def test_buttons_by_group_and_state(self):
        submit = "state != 'draft' or requester_id != uid"
        approve = "state != 'submitted' or approver_id != uid"
        reject = "state != 'submitted' or approver_id != uid"
        pay = "state != 'approved'"
        # Ninguno de estos usuarios tiene permisos de Contabilidad: no ven el botón para abrir el pago.
        self.assertEqual(self._form_buttons(self.requester), {"action_submit": submit})
        self.assertEqual(
            self._form_buttons(self.approver),
            {"action_submit": submit, "action_approve": approve, "action_reject": reject},
        )
        self.assertEqual(self._form_buttons(self.treasurer), {"action_submit": submit, "action_mark_paid": pay})
        accountant = self._create_user(
            "contabilidad_test", self.env.ref("base.group_user") | self.env.ref("account.group_account_invoice")
        )
        self.assertEqual(self._form_buttons(accountant).get("action_view_payment"), "not payment_id")
