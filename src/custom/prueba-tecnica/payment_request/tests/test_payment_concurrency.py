from unittest.mock import patch

from odoo import SUPERUSER_ID, api, sql_db
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.payment_request.models.payment_request import PaymentRequest

from .common import PaymentRequestCommon

QUIET = {"tracking_disable": True, "mail_create_nolog": True, "mail_create_nosubscribe": True}


@tagged("post_install", "-at_install")
class TestPaymentConcurrency(PaymentRequestCommon):
    """Tramo C: si dos personas actúan a la vez sobre la misma solicitud, solo una gana.

    El bloqueo lo hace PostgreSQL (SELECT ... FOR UPDATE NOWAIT). Para probarlo de verdad hacen
    falta dos conexiones independientes y datos confirmados, que se borran al terminar.
    """

    def _committed_request(self):
        db = sql_db.db_connect(self.env.cr.dbname)
        with db.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, QUIET)
            partner = env["res.partner"].create({"name": "Proveedor de la prueba de concurrencia"})
            request = env["payment.request"].create(
                {"partner_id": partner.id, "amount": 10.0, "concept": "Prueba de concurrencia"}
            )
            ids = request.id, partner.id
        self.addCleanup(self._delete_committed, *ids)
        return ids[0]

    def _delete_committed(self, request_id, partner_id):
        with sql_db.db_connect(self.env.cr.dbname).cursor() as cr:
            cr.execute("DELETE FROM payment_request WHERE id = %s", [request_id])
            cr.execute("DELETE FROM res_partner WHERE id = %s", [partner_id])

    def test_second_person_gets_an_immediate_notice(self):
        request_id = self._committed_request()
        db = sql_db.db_connect(self.env.cr.dbname)
        with db.cursor() as first, db.cursor() as second:
            # La primera persona está procesando la solicitud: tiene la fila bloqueada.
            first.execute("SELECT id FROM payment_request WHERE id = %s FOR UPDATE", [request_id])
            env_second = api.Environment(second, SUPERUSER_ID, {})
            with self.assertRaises(UserError) as error:
                env_second["payment.request"].browse(request_id)._lock_for_update()
            self.assertIn("Otra persona está procesando esta solicitud", str(error.exception))
            second.rollback()
            first.rollback()

    def test_lock_is_free_when_nobody_else_has_it(self):
        request_id = self._committed_request()
        with sql_db.db_connect(self.env.cr.dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["payment.request"].browse(request_id)._lock_for_update()
            cr.rollback()

    def test_every_state_change_takes_the_lock_before_doing_anything(self):
        """Enviar, aprobar, rechazar y pagar pasan por el bloqueo antes de cambiar nada."""
        draft = self._new_request()
        submitted = self._new_request()
        submitted.action_submit()
        approved = self._approved()
        journal = self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", self.company.id)], limit=1
        )
        busy = UserError("Otra persona está procesando esta solicitud.")
        with patch.object(PaymentRequest, "_lock_for_update", autospec=True, side_effect=busy) as lock:
            with self.assertRaises(UserError):
                draft.action_submit()
            with self.assertRaises(UserError):
                submitted.with_user(self.approver).action_approve()
            with self.assertRaises(UserError):
                self.env["payment.request.reject.wizard"].with_user(self.approver).create(
                    {"request_id": submitted.id, "reason": "Falta la factura"}
                ).action_confirm()
            with self.assertRaises(UserError):
                self.env["payment.request.pay.wizard"].with_user(self.treasurer).create(
                    {"request_id": approved.id, "journal_id": journal.id}
                ).action_confirm()
        self.assertEqual(lock.call_count, 4)
        self.assertEqual(draft.state, "draft")
        self.assertEqual(submitted.state, "submitted")
        self.assertFalse(submitted.reject_reason)
        self.assertEqual(approved.state, "approved")
        self.assertFalse(approved.payment_id)
