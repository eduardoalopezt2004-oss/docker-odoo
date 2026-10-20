from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from .common import PaymentRequestCommon

VES_PER_USD = 40.0
OLD_VES_PER_USD = 36.5


@tagged("post_install", "-at_install")
class TestPaymentCurrency(PaymentRequestCommon):
    """Tramo C: solicitud en USD pagada desde un diario en VES, a la tasa de la fecha del pago."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.usd = cls.env.ref("base.USD")
        cls.ves = cls.env.ref("base.VES")
        (cls.usd | cls.ves).active = True
        today = fields.Date.today()
        cls.pay_date = today - timedelta(days=1)
        cls.old_date = today - timedelta(days=5)
        # Hay una tasa anterior (old_date), pero no la de este día: no se debe usar la anterior.
        cls.no_rate_date = today - timedelta(days=3)
        cls._set_ves_per_usd(cls.pay_date, VES_PER_USD)
        cls._set_ves_per_usd(cls.old_date, OLD_VES_PER_USD)
        company_currency = cls.company.currency_id
        cls.ves_journal = cls.env["account.journal"].create(
            {
                "name": "Banco en bolívares C",
                "type": "bank",
                "code": "BVESC",
                "company_id": cls.company.id,
                "currency_id": cls.ves.id if cls.ves != company_currency else False,
            }
        )
        cls.company_journal = cls.env["account.journal"].search(
            [
                ("type", "=", "bank"),
                ("company_id", "=", cls.company.id),
                ("currency_id", "in", [False, company_currency.id]),
            ],
            limit=1,
        ) or cls.env["account.journal"].create(
            {"name": "Banco C", "type": "bank", "code": "BNKC", "company_id": cls.company.id}
        )
        # Una moneda extranjera para la compañía (VES, o USD si la compañía está en bolívares) y un diario en ella.
        cls.foreign = cls.usd if company_currency == cls.ves else cls.ves
        cls.foreign_journal = (
            cls.ves_journal
            if cls.foreign == cls.ves
            else cls.env["account.journal"].create(
                {
                    "name": "Banco en dólares C",
                    "type": "bank",
                    "code": "BUSDC",
                    "company_id": cls.company.id,
                    "currency_id": cls.usd.id,
                }
            )
        )

    @classmethod
    def _set_ves_per_usd(cls, date, ves_per_usd, company=None):
        """Deja 1 USD = ves_per_usd VES en esa fecha, sea cual sea la moneda de la compañía.

        Las tasas de Odoo son unidades de la moneda por unidad de la moneda de la compañía.

        :param company: compañía de la tasa; por defecto, la de la prueba. Vacía, una tasa sin compañía.
        """
        company = cls.company if company is None else company
        company_currency = cls.company.currency_id
        if company_currency == cls.ves:
            rates = {cls.usd: 1.0 / ves_per_usd}
        elif company_currency == cls.usd:
            rates = {cls.ves: ves_per_usd}
        else:
            rates = {cls.usd: 1.0, cls.ves: ves_per_usd}
        for currency, rate in rates.items():
            cls.env["res.currency.rate"].create(
                {"currency_id": currency.id, "name": date, "rate": rate, "company_id": company.id}
            )

    def _wizard(self, request, journal, date):
        return (
            self.env["payment.request.pay.wizard"]
            .with_user(self.treasurer)
            .create({"request_id": request.id, "journal_id": journal.id, "payment_date": date})
        )

    def _payments(self, request):
        return self.env["account.payment"].sudo().search([("payment_request_id", "=", request.id)])

    def test_usd_request_paid_from_ves_journal_at_payment_date_rate(self):
        request = self._approved(currency_id=self.usd.id, amount=100.0)
        self._wizard(request, self.ves_journal, self.pay_date).action_confirm()
        self.assertEqual(request.state, "paid")
        payment = self._payments(request)
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.currency_id, self.ves)
        self.assertEqual(payment.amount, 4000.0)
        self.assertEqual(payment.date, self.pay_date)
        self.assertNotEqual(payment.state, "draft")
        # La solicitud sigue en dólares y guarda lo que se pagó y a qué tasa.
        self.assertEqual(request.amount, 100.0)
        self.assertEqual(request.currency_id, self.usd)
        as_treasurer = request.with_user(self.treasurer)
        self.assertEqual(as_treasurer.payment_currency_id, self.ves)
        self.assertEqual(as_treasurer.payment_amount, 4000.0)
        self.assertAlmostEqual(as_treasurer.payment_rate, VES_PER_USD, places=6)

    def test_rate_is_the_one_of_the_payment_date(self):
        request = self._approved(currency_id=self.usd.id, amount=100.0)
        self._wizard(request, self.ves_journal, self.old_date).action_confirm()
        self.assertEqual(self._payments(request).amount, 3650.0)
        self.assertAlmostEqual(request.payment_rate, OLD_VES_PER_USD, places=6)

    def test_missing_rate_on_payment_date_blocks_payment(self):
        """Hay una tasa de días antes, pero no la del día del pago: no se paga con la vieja."""
        request = self._approved(currency_id=self.usd.id, amount=100.0)
        with self.assertRaises(UserError) as error:
            self._wizard(request, self.ves_journal, self.no_rate_date).action_confirm()
        self.assertIn("tasa", str(error.exception))
        self.assertIn(self.no_rate_date.strftime("%d/%m/%Y"), str(error.exception))
        self.assertEqual(request.state, "approved")
        self.assertFalse(self._payments(request))
        self.assertFalse(request.payment_rate)

    def test_rate_check_looks_at_the_rate_odoo_converts_with(self):
        """Odoo convierte con la tasa de la compañía aunque sea más vieja que una tasa sin compañía de ese día.

        Si la comprobación aceptara la tasa sin compañía, el pago saldría con la tasa vieja sin ningún aviso.
        """
        self._set_ves_per_usd(self.no_rate_date, 50.0, company=self.env["res.company"])
        request = self._approved(currency_id=self.usd.id, amount=100.0)
        with self.assertRaises(UserError) as error:
            self._wizard(request, self.ves_journal, self.no_rate_date).action_confirm()
        self.assertIn(self.no_rate_date.strftime("%d/%m/%Y"), str(error.exception))
        self.assertEqual(request.state, "approved")
        self.assertFalse(self._payments(request))

    def test_branch_pays_with_the_rates_of_its_main_company(self):
        """En Odoo 18 las tasas solo se cargan en la compañía principal: una sucursal paga con ellas."""
        branch = self.env["res.company"].create(
            {"name": "Sucursal C de prueba", "parent_id": self.company.id, "currency_id": self.company.currency_id.id}
        )
        requester = self._create_user("solicitante_sucursal_c", self.group_user, branch)
        request = self._new_request(requester, currency_id=self.usd.id, amount=100.0)
        self.assertEqual(request.company_id, branch)
        currency, amount, rate = request._get_payment_terms(self.ves_journal, self.pay_date)
        self.assertEqual(currency, self.ves)
        self.assertEqual(amount, 4000.0)
        self.assertAlmostEqual(rate, VES_PER_USD, places=6)

    def test_branch_can_pay_from_the_journals_of_its_main_company(self):
        """Como en Odoo 18, una sucursal puede pagar desde los diarios de su compañía principal, nunca desde los de otra."""
        branch = self.env["res.company"].create(
            {"name": "Sucursal de diarios C", "parent_id": self.company.id, "currency_id": self.company.currency_id.id}
        )
        treasurer = self._create_user("tesoreria_sucursal_c", self.group_user | self.treasury_group, branch)
        requester = self._create_user("solicitante_sucursal_diarios_c", self.group_user, branch)
        request = self._new_request(requester, currency_id=self.usd.id, amount=100.0)
        # El asistente le ofrece a Tesorería de la sucursal el banco en bolívares de la principal.
        domain = safe_eval(self.env["payment.request.pay.wizard"]._fields["journal_id"].domain, {"company_id": branch.id})
        self.assertIn(self.ves_journal, self.env["account.journal"].with_user(treasurer).search(domain))
        request._check_payment_journal(self.ves_journal)
        other = self.env["res.company"].create({"name": "Otra compañía C", "currency_id": self.company.currency_id.id})
        other_request = self._new_request(self._create_user("solicitante_otra_c", self.group_user, other))
        with self.assertRaises(UserError):
            other_request._check_payment_journal(self.ves_journal)

    def test_small_rate_is_stored_with_full_precision(self):
        """Una tasa chica (por ejemplo, de bolívares a dólares) se guarda completa y su texto no usa notación científica."""
        company_currency = self.company.currency_id
        request = self._approved(currency_id=self.foreign.id, amount=3650.0)
        self._wizard(request, self.company_journal, self.old_date).action_confirm()
        expected = self.env["res.currency"]._get_conversion_rate(
            self.foreign, company_currency, self.company, self.old_date
        )
        self.assertAlmostEqual(request.payment_rate, expected, places=12)
        Request = self.env["payment.request"]
        self.assertEqual(Request._format_rate(self.usd, self.ves, 40.0), "1 USD = 40 VES")
        self.assertEqual(Request._format_rate(self.usd, self.ves, 6.3e-05), "1 USD = 0.000063 VES")

    def test_same_foreign_currency_needs_the_rate_of_the_day(self):
        """Solicitud y diario en la misma moneda extranjera: el monto no cambia, pero el asiento en la moneda
        de la compañía se calcula con la tasa, así que también se exige la de ese día."""
        request = self._approved(currency_id=self.foreign.id, amount=100.0)
        with self.assertRaises(UserError) as error:
            self._wizard(request, self.foreign_journal, self.no_rate_date).action_confirm()
        self.assertIn(self.no_rate_date.strftime("%d/%m/%Y"), str(error.exception))
        self.assertEqual(request.state, "approved")
        self.assertFalse(self._payments(request))
        self._wizard(request, self.foreign_journal, self.pay_date).action_confirm()
        self.assertEqual(request.state, "paid")
        payment = self._payments(request)
        self.assertEqual(payment.currency_id, self.foreign)
        self.assertEqual(payment.amount, 100.0)
        self.assertEqual(request.payment_rate, 1.0)

    def test_wizard_shows_amount_and_rate_before_paying(self):
        request = self._approved(currency_id=self.usd.id, amount=100.0)
        wizard = self._wizard(request, self.ves_journal, self.pay_date)
        self.assertEqual(wizard.payment_currency_id, self.ves)
        self.assertEqual(wizard.payment_amount, 4000.0)
        self.assertAlmostEqual(wizard.rate, VES_PER_USD, places=6)
        self.assertFalse(wizard.rate_warning)
        # Sin tasa del día: el asistente avisa antes de confirmar y no muestra un monto.
        wizard.payment_date = self.no_rate_date
        self.assertIn("No hay tasa", wizard.rate_warning)
        self.assertFalse(wizard.payment_amount)

    def test_same_currency_needs_no_rate(self):
        """Solicitud y diario en la moneda de la compañía: no hay conversión ni tasa que exigir."""
        request = self._approved(amount=100.0)
        self._wizard(request, self.company_journal, self.no_rate_date).action_confirm()
        self.assertEqual(request.state, "paid")
        payment = self._payments(request)
        self.assertEqual(payment.amount, 100.0)
        self.assertEqual(payment.currency_id, request.currency_id)
        self.assertEqual(request.payment_rate, 1.0)

    def test_failed_payment_in_ves_leaves_request_approved(self):
        request = self._approved(currency_id=self.usd.id, amount=100.0)
        wizard = self._wizard(request, self.ves_journal, self.pay_date)
        with (
            patch(
                "odoo.addons.account.models.account_payment.AccountPayment.action_post",
                side_effect=UserError("falla al publicar"),
            ),
            self.assertRaises(UserError),
            self.cr.savepoint(),
        ):
            wizard.action_confirm()
        self.assertEqual(request.state, "approved")
        self.assertFalse(request.payment_id)
        self.assertFalse(request.payment_rate)
        self.assertFalse(self._payments(request))

    def test_report_shows_amount_paid_and_rate(self):
        request = self._approved(currency_id=self.usd.id, amount=100.0)
        self._wizard(request, self.ves_journal, self.pay_date).action_confirm()
        html = self.env["ir.actions.report"]._render_qweb_html("payment_request.report_payment_request", request.ids)[0]
        html = html.decode() if isinstance(html, bytes) else str(html)
        self.assertIn("Tasa", html)
        self.assertIn("1 USD", html)
        self.assertIn("VES", html)
