from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

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

    @classmethod
    def _set_ves_per_usd(cls, date, ves_per_usd):
        """Deja 1 USD = ves_per_usd VES en esa fecha, sea cual sea la moneda de la compañía.

        Las tasas de Odoo son unidades de la moneda por unidad de la moneda de la compañía.
        """
        company_currency = cls.company.currency_id
        if company_currency == cls.ves:
            rates = {cls.usd: 1.0 / ves_per_usd}
        elif company_currency == cls.usd:
            rates = {cls.ves: ves_per_usd}
        else:
            rates = {cls.usd: 1.0, cls.ves: ves_per_usd}
        for currency, rate in rates.items():
            cls.env["res.currency.rate"].create(
                {"currency_id": currency.id, "name": date, "rate": rate, "company_id": cls.company.id}
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
