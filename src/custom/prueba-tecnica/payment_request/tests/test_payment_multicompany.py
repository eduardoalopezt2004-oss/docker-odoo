from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import PaymentRequestCommon


@tagged("post_install", "-at_install")
class TestPaymentMultiCompany(PaymentRequestCommon):
    """Tramo C: solicitudes y niveles por compañía, con reglas de registro."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env["res.company"].create(
            {"name": "Transporte Andina de prueba", "currency_id": cls.company.currency_id.id}
        )
        cls.requester_b = cls._create_user("solicitante_b_c", cls.group_user, cls.company_b)
        cls.approver_b = cls._create_user("aprobador_b_c", cls.group_user | cls.approver_group, cls.company_b)
        cls.level_b = cls.env["payment.approval.level"].create(
            {"name": "General B", "min_amount": 0.0, "approver_id": cls.approver_b.id, "company_id": cls.company_b.id}
        )
        # Aprobador con acceso a las dos compañías.
        cls.approver_ab = cls._create_user(
            "aprobador_ab_c",
            cls.group_user | cls.approver_group | cls.env.ref("base.group_multi_company"),
            cls.company | cls.company_b,
        )

    def test_request_belongs_to_the_current_company(self):
        self.assertEqual(self._new_request().company_id, self.company)
        self.assertEqual(self._new_request(self.requester_b).company_id, self.company_b)

    def test_user_of_company_b_sees_nothing_of_company_a(self):
        request_a = self._approved()
        request_b = self._new_request(self.requester_b)
        for user in (self.requester_b, self.approver_b):
            with self.subTest(user=user.login):
                Request = self.env["payment.request"].with_user(user)
                found = Request.search([])
                self.assertIn(request_b, found)
                self.assertNotIn(request_a, found)
                with self.assertRaises(AccessError):
                    request_a.with_user(user).read(["amount"])
                levels = self.env["payment.approval.level"].with_user(user).search([])
                self.assertIn(self.level_b, levels)
                self.assertNotIn(self.level, levels)
                with self.assertRaises(AccessError):
                    self.level.with_user(user).read(["min_amount"])

    def test_user_with_both_companies_sees_only_the_active_ones(self):
        request_a = self._new_request()
        request_b = self._new_request(self.requester_b)
        Request = self.env["payment.request"].with_user(self.approver_ab)
        only_a = Request.with_context(allowed_company_ids=self.company.ids).search([])
        self.assertIn(request_a, only_a)
        self.assertNotIn(request_b, only_a)
        both = Request.with_context(allowed_company_ids=(self.company | self.company_b).ids).search([])
        self.assertIn(request_a, both)
        self.assertIn(request_b, both)

    def test_level_of_the_request_company_is_used(self):
        request_b = self._new_request(self.requester_b)
        request_b.action_submit()
        self.assertEqual(request_b.approver_id, self.approver_b)
        # Sin niveles en la compañía B no se envía, aunque la compañía A tenga.
        self.level_b.unlink()
        other_b = self._new_request(self.requester_b)
        with self.assertRaises(UserError):
            other_b.action_submit()
        self.assertEqual(other_b.state, "draft")

    def test_level_approver_must_have_access_to_its_company(self):
        with self.assertRaises(ValidationError):
            self.env["payment.approval.level"].create(
                {"name": "Mal", "min_amount": 500.0, "approver_id": self.approver.id, "company_id": self.company_b.id}
            )

    def test_company_cannot_change_after_submit(self):
        request = self._new_request()
        request.action_submit()
        with self.assertRaises(UserError):
            request.sudo().write({"company_id": self.company_b.id})
        self.assertEqual(request.company_id, self.company)

    def test_search_view_groups_by_company_for_multi_company_users(self):
        search = self.env["payment.request"].with_user(self.approver_ab).get_views([(False, "search")])
        arch = search["views"]["search"]["arch"]
        self.assertIn("'group_by': 'company_id'", arch)
