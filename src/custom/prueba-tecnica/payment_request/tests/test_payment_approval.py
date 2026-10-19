from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestPaymentApproval(TransactionCase):
    """Tramo B: niveles de aprobación, aprobador asignado, rechazo con motivo, pago y reporte."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env["res.partner"].create({"name": "Proveedor B de prueba"})
        group_user = cls.env.ref("base.group_user")
        approver_group = cls.env.ref("payment_request.group_payment_approver")
        cls.requester = cls._create_user("solicitante_b", group_user)
        cls.chief = cls._create_user("jefe_area_b", group_user | approver_group)
        cls.manager = cls._create_user("gerente_b", group_user | approver_group)
        cls.treasurer = cls._create_user("tesoreria_b", group_user | cls.env.ref("payment_request.group_payment_treasury"))
        cls.admin = cls._create_user("admin_b", group_user | cls.env.ref("base.group_system"))
        Level = cls.env["payment.approval.level"]
        cls.level_chief = Level.create({"name": "Jefe de área", "min_amount": 0.0, "approver_id": cls.chief.id})
        cls.level_manager = Level.create({"name": "Gerencia", "min_amount": 1000.0, "approver_id": cls.manager.id})
        # Moneda inventada con tasa fija: 1 unidad de la compañía = 0.5 XXY, o sea 1 XXY = 2 de la compañía.
        cls.foreign = cls.env["res.currency"].create(
            {
                "name": "XXY",
                "symbol": "X",
                "rounding": 0.01,
                "rate_ids": [Command.create({"name": fields.Date.today() - timedelta(days=1), "rate": 0.5, "company_id": cls.company.id})],
            }
        )
        cls.journal = cls._bank_journal()

    @classmethod
    def _create_user(cls, login, groups):
        return (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create({"name": login, "login": login, "groups_id": [Command.set(groups.ids)]})
        )

    @classmethod
    def _bank_journal(cls):
        journal = cls.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", cls.company.id)], limit=1
        )
        return journal or cls.env["account.journal"].create(
            {"name": "Banco B de prueba", "type": "bank", "code": "PRBB", "company_id": cls.company.id}
        )

    def _new_request(self, amount=150.0, user=None, **vals):
        values = {"partner_id": self.partner.id, "amount": amount, "concept": "Compra de repuestos"}
        values.update(vals)
        return self.env["payment.request"].with_user(user or self.requester).create(values)

    def _submitted(self, amount=150.0, **vals):
        request = self._new_request(amount, **vals)
        request.action_submit()
        return request

    def _approved(self, amount=150.0):
        request = self._submitted(amount)
        request.with_user(request.approver_id).action_approve()
        return request

    def _reject(self, request, user, reason="Falta la factura"):
        wizard = (
            self.env["payment.request.reject.wizard"]
            .with_user(user)
            .create({"request_id": request.id, "reason": reason})
        )
        return wizard.action_confirm()

    def _pay(self, request, user=None):
        wizard = (
            self.env["payment.request.pay.wizard"]
            .with_user(user or self.treasurer)
            .create({"request_id": request.id, "journal_id": self.journal.id})
        )
        return wizard.action_confirm()

    # Niveles de aprobación

    def test_level_is_chosen_by_amount(self):
        cases = [
            (0.01, self.chief),
            (999.99, self.chief),
            (1000.0, self.manager),
            (250000.0, self.manager),
        ]
        for amount, approver in cases:
            with self.subTest(amount=amount):
                request = self._submitted(amount)
                self.assertEqual(request.approver_id, approver)

    def test_level_compares_in_company_currency(self):
        # 600 XXY son 1200 en la moneda de la compañía: nivel de Gerencia.
        request = self._submitted(600.0, currency_id=self.foreign.id)
        self.assertEqual(request.approver_id, self.manager)
        # 400 XXY son 800: nivel del jefe de área.
        self.assertEqual(self._submitted(400.0, currency_id=self.foreign.id).approver_id, self.chief)

    def test_no_level_for_amount_blocks_submit(self):
        self.level_chief.unlink()
        request = self._new_request(500.0)
        with self.assertRaises(UserError) as error:
            request.action_submit()
        self.assertIn("nivel de aprobación", str(error.exception))
        self.assertEqual(request.state, "draft")
        self.assertFalse(request.approver_id)
        # Con monto que sí cubre un nivel, el envío funciona.
        self.assertEqual(self._submitted(1500.0).approver_id, self.manager)
        # Tampoco se salta con una escritura directa del estado.
        with self.assertRaises(UserError):
            request.write({"state": "submitted"})
        self.assertEqual(request.state, "draft")

    def test_submit_fails_if_approver_is_requester(self):
        request = self._new_request(150.0, user=self.chief)
        with self.assertRaises(UserError) as error:
            request.action_submit()
        self.assertIn("aprobador", str(error.exception))
        self.assertEqual(request.state, "draft")
        self.assertFalse(request.approver_id)
        # Una solicitud grande del mismo jefe sí va a Gerencia.
        big = self._new_request(5000.0, user=self.chief)
        big.action_submit()
        self.assertEqual(big.approver_id, self.manager)

    def test_level_constraints(self):
        Level = self.env["payment.approval.level"]
        with self.assertRaises(ValidationError):
            Level.create({"name": "Negativo", "min_amount": -1.0, "approver_id": self.chief.id})
        with self.assertRaises(ValidationError):
            Level.create({"name": "Sin grupo", "min_amount": 50.0, "approver_id": self.requester.id})
        # Dos niveles con el mismo monto mínimo en la misma compañía no tienen sentido.
        with self.assertRaises(Exception), mute_logger("odoo.sql_db"), self.cr.savepoint():
            Level.create({"name": "Repetido", "min_amount": 1000.0, "approver_id": self.chief.id})

    def test_level_access(self):
        Level = self.env["payment.approval.level"]
        # Cualquier solicitante puede leerlos (el envío los consulta), pero no cambiarlos.
        self.assertEqual(Level.with_user(self.requester).search([("company_id", "=", self.company.id)]), self.level_chief | self.level_manager)
        for operation in ("create", "write", "unlink"):
            with self.subTest(operation=operation):
                self.assertFalse(Level.with_user(self.requester).has_access(operation))
        for operation in ("create", "write", "unlink"):
            with self.subTest(admin=operation):
                self.assertTrue(Level.with_user(self.admin).has_access(operation))

    def test_assigned_approver_does_not_change_with_levels(self):
        request = self._submitted(150.0)
        self.assertEqual(request.approver_id, self.chief)
        self.level_chief.approver_id = self.manager
        self.assertEqual(request.approver_id, self.chief)

    # Actividad y aprobación

    def test_submit_creates_activity_for_approver(self):
        request = self._submitted(150.0)
        activities = request.activity_ids
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.user_id, self.chief)
        self.assertEqual(activities.activity_type_id, self.env.ref("mail.mail_activity_data_todo"))

    def test_only_assigned_approver_approves(self):
        request = self._submitted(150.0)
        with self.assertRaises(AccessError):
            request.with_user(self.manager).action_approve()
        with self.assertRaises(AccessError):
            request.with_user(self.manager).write({"state": "approved"})
        self.assertEqual(request.state, "submitted")
        request.with_user(self.chief).action_approve()
        self.assertEqual(request.state, "approved")

    def test_approval_records_who_and_when(self):
        request = self._submitted(150.0)
        self.assertFalse(request.approval_date)
        before = fields.Datetime.now()
        request.with_user(self.chief).action_approve()
        self.assertEqual(request.approver_id, self.chief)
        self.assertGreaterEqual(request.approval_date, before - timedelta(seconds=5))
        self.assertFalse(request.activity_ids)

    def test_system_fields_cannot_be_written_by_users(self):
        request = self._new_request()
        for user in (self.requester, self.chief, self.treasurer):
            for vals in ({"approver_id": self.chief.id}, {"approval_date": fields.Datetime.now()}, {"reject_reason": "x"}):
                with self.subTest(user=user.login, vals=vals):
                    with self.assertRaises(UserError):
                        request.with_user(user).write(vals)
        with self.assertRaises(UserError):
            self.env["payment.request"].with_user(self.requester).create(
                {"partner_id": self.partner.id, "amount": 10.0, "concept": "x", "approver_id": self.chief.id}
            )
        submitted = self._submitted()
        with self.assertRaises(UserError):
            submitted.with_user(self.manager).write({"approver_id": self.manager.id})
        self.assertEqual(submitted.approver_id, self.chief)

    # Rechazo con motivo

    def test_reject_opens_wizard_only_for_assigned_approver(self):
        request = self._submitted(150.0)
        action = request.with_user(self.chief).action_reject()
        self.assertEqual(action["res_model"], "payment.request.reject.wizard")
        self.assertEqual(action["target"], "new")
        self.assertEqual(request.state, "submitted")
        with self.assertRaises(AccessError):
            request.with_user(self.manager).action_reject()
        with self.assertRaises(AccessError):
            request.with_user(self.requester).action_reject()

    def test_reject_requires_reason(self):
        request = self._submitted(150.0)
        for reason in ("", "   ", False):
            with self.subTest(reason=reason):
                with self.assertRaises((ValidationError, UserError)):
                    self._reject(request, self.chief, reason)
        self.assertEqual(request.state, "submitted")
        self.assertFalse(request.reject_reason)

    def test_reject_stores_reason_and_notifies_in_chatter(self):
        request = self._submitted(150.0)
        self._reject(request, self.chief, "Falta la factura del proveedor")
        self.assertEqual(request.state, "rejected")
        self.assertEqual(request.reject_reason, "Falta la factura del proveedor")
        self.assertFalse(request.activity_ids)
        # El solicitante ve el motivo en el chatter y en el campo.
        as_requester = request.with_user(self.requester)
        self.assertEqual(as_requester.reject_reason, "Falta la factura del proveedor")
        messages = request.sudo().message_ids.filtered(lambda m: "Falta la factura del proveedor" in (m.body or ""))
        self.assertTrue(messages)
        self.assertEqual(messages[0].author_id, self.chief.partner_id)

    def test_wizard_reject_by_unassigned_approver_fails(self):
        request = self._submitted(150.0)
        with self.assertRaises(AccessError):
            self._reject(request, self.manager)
        self.assertEqual(request.state, "submitted")

    def test_reject_state_needs_reason(self):
        request = self._submitted(150.0)
        with self.assertRaises(UserError):
            request.with_user(self.chief).write({"state": "rejected"})
        self.assertEqual(request.state, "submitted")

    def test_wizards_are_limited_to_their_group(self):
        request = self._approved()
        with self.assertRaises(AccessError):
            self.env["payment.request.reject.wizard"].with_user(self.requester).create(
                {"request_id": request.id, "reason": "x"}
            )
        with self.assertRaises(AccessError):
            self.env["payment.request.pay.wizard"].with_user(self.chief).create(
                {"request_id": request.id, "journal_id": self.journal.id}
            )

    # Pago

    def test_pay_creates_vendor_payment_linked_to_request(self):
        request = self._approved(150.0)
        self._pay(request)
        self.assertEqual(request.state, "paid")
        payment = request.payment_id
        self.assertTrue(payment)
        self.assertEqual(payment.payment_type, "outbound")
        self.assertEqual(payment.partner_type, "supplier")
        self.assertEqual(payment.partner_id, self.partner)
        self.assertEqual(payment.amount, 150.0)
        self.assertEqual(payment.currency_id, request.currency_id)
        self.assertEqual(payment.journal_id, self.journal)
        self.assertEqual(payment.payment_request_id, request)
        # Registrado en contabilidad: el asiento queda publicado.
        self.assertEqual(payment.move_id.state, "posted")

    def test_treasury_pays_without_accounting_groups(self):
        """El pago usa sudo() acotado a crear y publicar ese pago: Tesorería no necesita grupos de Contabilidad."""
        self.assertFalse(self.treasurer.has_group("account.group_account_user"))
        self.assertFalse(self.treasurer.has_group("account.group_account_invoice"))
        self.assertFalse(self.env["account.payment"].with_user(self.treasurer).has_access("create"))
        request = self._approved()
        self._pay(request)
        self.assertEqual(request.state, "paid")

    def test_cannot_pay_twice(self):
        request = self._approved()
        self._pay(request)
        payments = self.env["account.payment"].search([("payment_request_id", "=", request.id)])
        self.assertEqual(len(payments), 1)
        with self.assertRaises(UserError):
            self._pay(request)
        with self.assertRaises(UserError):
            request.with_user(self.treasurer).action_mark_paid()
        self.assertEqual(self.env["account.payment"].search_count([("payment_request_id", "=", request.id)]), 1)

    def test_can_only_pay_approved(self):
        for request in (self._new_request(), self._submitted()):
            with self.subTest(state=request.state):
                with self.assertRaises(UserError):
                    self._pay(request)
                self.assertFalse(request.payment_id)

    def test_paid_state_needs_payment(self):
        request = self._approved()
        with self.assertRaises(UserError):
            request.with_user(self.treasurer).write({"state": "paid"})
        self.assertEqual(request.state, "approved")

    def test_pay_is_all_or_nothing(self):
        """Si el pago falla, la solicitud no queda como pagada ni con pago a medias."""
        request = self._approved()
        wizard = (
            self.env["payment.request.pay.wizard"]
            .with_user(self.treasurer)
            .create({"request_id": request.id, "journal_id": self.journal.id})
        )
        # Se fuerza el fallo al publicar el pago para comprobar que no queda nada a medias.
        with patch("odoo.addons.account.models.account_payment.AccountPayment.action_post", side_effect=UserError("falla")):
            with self.assertRaises(UserError), self.cr.savepoint():
                wizard.action_confirm()
        self.assertEqual(request.state, "approved")
        self.assertFalse(request.payment_id)
        self.assertFalse(self.env["account.payment"].search([("payment_request_id", "=", request.id)]))

    def test_view_payment_action(self):
        request = self._approved()
        with self.assertRaises(UserError):
            request.action_view_payment()
        self._pay(request)
        action = request.with_user(self.requester).action_view_payment()
        self.assertEqual(action["res_model"], "account.payment")
        self.assertEqual(action["res_id"], request.payment_id.id)

    # Reporte

    def test_report_shows_approver_and_date(self):
        request = self._approved(150.0)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "payment_request.report_payment_request", request.ids
        )[0].decode()
        self.assertIn(request.name, html)
        self.assertIn(self.partner.name, html)
        self.assertIn(self.chief.name, html)
        self.assertIn("Aprobada por", html)
        self.assertIn(request.concept, html)
        # Una solicitud sin aprobar no muestra aprobador.
        draft = self._new_request()
        draft_html = self.env["ir.actions.report"]._render_qweb_html(
            "payment_request.report_payment_request", draft.ids
        )[0].decode()
        self.assertNotIn("Aprobada por", draft_html)

    # Vistas

    def test_levels_and_wizard_views_exist(self):
        View = self.env["ir.ui.view"]
        for model, view_type in (
            ("payment.approval.level", "list"),
            ("payment.approval.level", "form"),
            ("payment.request.reject.wizard", "form"),
            ("payment.request.pay.wizard", "form"),
        ):
            with self.subTest(model=model, view_type=view_type):
                self.assertTrue(View.search([("model", "=", model), ("type", "=", view_type)]))
