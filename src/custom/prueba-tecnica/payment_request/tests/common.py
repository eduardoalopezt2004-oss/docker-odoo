from odoo import Command
from odoo.tests import TransactionCase


class PaymentRequestCommon(TransactionCase):
    """Datos comunes de las pruebas del tramo C: un solicitante, un aprobador con un nivel general
    y Tesorería, todos en la compañía de la prueba."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env["res.partner"].create({"name": "Proveedor C de prueba"})
        cls.group_user = cls.env.ref("base.group_user")
        cls.approver_group = cls.env.ref("payment_request.group_payment_approver")
        cls.treasury_group = cls.env.ref("payment_request.group_payment_treasury")
        cls.requester = cls._create_user("solicitante_c", cls.group_user)
        cls.approver = cls._create_user("aprobador_c", cls.group_user | cls.approver_group)
        cls.treasurer = cls._create_user("tesoreria_c", cls.group_user | cls.treasury_group)
        cls.level = cls.env["payment.approval.level"].create(
            {"name": "General C", "min_amount": 0.0, "approver_id": cls.approver.id}
        )

    @classmethod
    def _create_user(cls, login, groups, companies=None):
        companies = companies or cls.company
        return (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": login,
                    "login": login,
                    "email": f"{login}@example.com",
                    "groups_id": [Command.set(groups.ids)],
                    "company_id": companies[0].id,
                    "company_ids": [Command.set(companies.ids)],
                }
            )
        )

    def _new_request(self, user=None, **vals):
        values = {"partner_id": self.partner.id, "amount": 150.0, "concept": "Compra de repuestos"}
        values.update(vals)
        return self.env["payment.request"].with_user(user or self.requester).create(values)

    def _approved(self, user=None, approver=None, **vals):
        request = self._new_request(user, **vals)
        request.action_submit()
        request.with_user(approver or self.approver).action_approve()
        return request
