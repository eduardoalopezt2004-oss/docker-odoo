import re

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import PaymentRequestCommon


@tagged("post_install", "-at_install")
class TestPaymentNumbering(PaymentRequestCommon):
    """Tramo C: contador por compañía con código (DA/SP/2026/0001) y contador general sin código."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.year = fields.Date.today().year
        cls.company_b = cls.env["res.company"].create(
            {"name": "Transporte Andina de numeración", "currency_id": cls.company.currency_id.id}
        )
        cls.requester_b = cls._create_user("solicitante_num_b", cls.group_user, cls.company_b)

    def test_company_without_code_keeps_the_general_counter(self):
        self.assertFalse(self.company.payment_request_code)
        first = self._new_request()
        second = self._new_request()
        self.assertRegex(first.name, r"^SP/%s/\d{4}$" % self.year)
        self.assertEqual(int(second.name[-4:]), int(first.name[-4:]) + 1)

    def test_each_company_with_code_has_its_own_consecutive_counter(self):
        self.company.payment_request_code = "DA"
        self.company_b.payment_request_code = "TA"
        names = [
            self._new_request().name,
            self._new_request(self.requester_b).name,
            self._new_request().name,
        ]
        self.assertEqual(
            names,
            [f"DA/SP/{self.year}/0001", f"TA/SP/{self.year}/0001", f"DA/SP/{self.year}/0002"],
        )

    def test_changing_the_code_only_affects_new_requests(self):
        self.company.payment_request_code = "DA"
        first = self._new_request()
        self.company.payment_request_code = "DX"
        second = self._new_request()
        self.assertEqual(first.name, f"DA/SP/{self.year}/0001")
        self.assertEqual(second.name, f"DX/SP/{self.year}/0002")

    def test_code_format_and_uniqueness(self):
        for code in ("da", "D A", "DEMASIADO", "D-A"):
            with self.subTest(code=code), self.assertRaises(ValidationError):
                self.company.payment_request_code = code
        self.company.payment_request_code = "DA"
        with self.assertRaises(ValidationError):
            self.company_b.payment_request_code = "DA"

    def test_requester_without_admin_rights_gets_a_number(self):
        """El contador de la compañía lo crea el sistema, aunque quien pide no pueda crear secuencias."""
        self.company_b.payment_request_code = "TA"
        request = self._new_request(self.requester_b)
        self.assertTrue(re.match(r"^TA/SP/%s/\d{4}$" % self.year, request.name), request.name)
        self.assertFalse(self.env["ir.sequence"].with_user(self.requester_b).has_access("create"))

    def test_numbers_are_unique_in_the_database(self):
        constraints = dict((name, sql) for name, sql, _message in self.env["payment.request"]._sql_constraints)
        self.assertEqual(constraints.get("name_uniq"), "unique(name)")
