import time
from unittest.mock import patch

from odoo import SUPERUSER_ID, Command, api, sql_db
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from odoo.addons.payment_request.models.payment_request import PaymentRequest

from .common import PaymentRequestCommon

QUIET = {"tracking_disable": True, "mail_create_nolog": True, "mail_create_nosubscribe": True}
# Si alguien quitara NOWAIT, la segunda conexión esperaría a la primera, que está en este mismo hilo: la
# prueba se colgaría. Con este límite falla a los 5 segundos.
SET_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


@tagged("post_install", "-at_install")
class TestPaymentConcurrency(PaymentRequestCommon):
    """Tramo C: si dos personas actúan a la vez sobre la misma solicitud, solo una gana.

    El bloqueo lo hace PostgreSQL (SELECT ... FOR UPDATE NOWAIT). Para probarlo de verdad hacen
    falta dos conexiones independientes y datos confirmados, que se borran al terminar.
    """

    @classmethod
    def setUpClass(cls):
        # El aprobador de la prueba de punta a punta se confirma antes de que la clase abra su transacción.
        # Crear un usuario escribe en registros compartidos (por ejemplo, el resumen por correo de
        # digest): si esa transacción ya los tuviera bloqueados, la conexión aparte esperaría a la prueba,
        # que a su vez la espera a ella. Se borra al final, cuando esa transacción ya se cerró.
        cls.committed_approver_id = cls._create_committed_approver()
        cls.addClassCleanup(cls._delete_committed_user, cls.committed_approver_id)
        super().setUpClass()

    @classmethod
    def _create_committed_approver(cls):
        with sql_db.db_connect(get_db_name()).cursor() as cr:
            cr.execute(SET_LOCK_TIMEOUT)
            env = api.Environment(cr, SUPERUSER_ID, QUIET)
            # También el rango del año del contador de solicitudes: si lo creara después una solicitud
            # confirmada en una conexión aparte, la transacción de la clase, que no lo ve, intentaría crearlo
            # otra vez y chocaría con su índice único. Solo consume un número del contador.
            env["ir.sequence"].next_by_code("payment.request")
            groups = env.ref("base.group_user") | env.ref("payment_request.group_payment_approver")
            approver = (
                env["res.users"]
                .with_context(no_reset_password=True)
                .create(
                    {
                        "name": "Aprobador de la prueba de concurrencia",
                        "login": "aprobador_concurrencia_c",
                        "email": "aprobador_concurrencia_c@example.com",
                        "groups_id": [Command.set(groups.ids)],
                    }
                )
            )
            return approver.id

    @classmethod
    def _delete_committed_user(cls, user_id):
        with sql_db.db_connect(get_db_name()).cursor() as cr:
            cr.execute(SET_LOCK_TIMEOUT)
            env = api.Environment(cr, SUPERUSER_ID, {})
            user = env["res.users"].browse(user_id)
            partner = user.partner_id
            user.unlink()
            partner.unlink()

    def _committed_request(self):
        db = sql_db.db_connect(self.env.cr.dbname)
        with db.cursor() as cr:
            cr.execute(SET_LOCK_TIMEOUT)
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
            cr.execute(SET_LOCK_TIMEOUT)
            cr.execute("DELETE FROM payment_request WHERE id = %s", [request_id])
            cr.execute("DELETE FROM res_partner WHERE id = %s", [partner_id])

    def _committed_submitted_request(self):
        """Solicitud enviada, asignada al aprobador confirmado, para que la vean otras conexiones.

        Pasa a enviada por SQL: el envío normal necesita un nivel de aprobación confirmado, que cambiaría
        el resultado de las demás pruebas mientras exista.
        """
        request_id = self._committed_request()
        with sql_db.db_connect(get_db_name()).cursor() as cr:
            cr.execute(SET_LOCK_TIMEOUT)
            cr.execute(
                "UPDATE payment_request SET state = 'submitted', approver_id = %s WHERE id = %s",
                [self.committed_approver_id, request_id],
            )
        return request_id

    def test_second_person_gets_an_immediate_notice(self):
        request_id = self._committed_request()
        db = sql_db.db_connect(self.env.cr.dbname)
        with db.cursor() as first, db.cursor() as second:
            # La primera persona está procesando la solicitud: tiene la fila bloqueada.
            first.execute("SELECT id FROM payment_request WHERE id = %s FOR UPDATE", [request_id])
            second.execute(SET_LOCK_TIMEOUT)
            env_second = api.Environment(second, SUPERUSER_ID, {})
            start = time.monotonic()
            # El choque es esperado y se convierte en aviso: no debe quedar como error en el registro.
            with self.assertNoLogs("odoo.sql_db", level="ERROR"), self.assertRaises(UserError) as error:
                env_second["payment.request"].browse(request_id)._lock_for_update()
            # Al instante: la segunda persona no espera a que termine la primera.
            self.assertLess(time.monotonic() - start, 1.0)
            self.assertIn("Otra persona está procesando esta solicitud", str(error.exception))
            second.rollback()
            first.rollback()

    def test_two_tabs_of_the_approver_only_one_wins(self):
        """El aprobador aprueba en una pestaña y rechaza en otra al mismo tiempo: gana la primera.

        Desde el tramo B solo el aprobador asignado aprueba o rechaza, así que «dos aprobadores a la vez» es
        la misma persona en dos pestañas o dispositivos. Cada una es una conexión propia a la base, y aquí
        se usan los métodos reales, no solo el bloqueo.
        """
        request_id = self._committed_submitted_request()
        approver_id = self.committed_approver_id
        db = sql_db.db_connect(self.env.cr.dbname)
        with db.cursor() as first, db.cursor() as second:
            second.execute(SET_LOCK_TIMEOUT)
            env_first = api.Environment(first, approver_id, QUIET)
            env_second = api.Environment(second, approver_id, QUIET)
            # Primera pestaña: aprueba y su transacción sigue abierta.
            env_first["payment.request"].browse(request_id).action_approve()
            # Segunda pestaña, a la vez: rechazar recibe el aviso y no cambia nada.
            with self.assertRaises(UserError) as error:
                env_second["payment.request"].browse(request_id)._reject("Falta la factura")
            self.assertIn("Otra persona está procesando esta solicitud", str(error.exception))
            second.rollback()
            first.commit()
            # La primera ya terminó: si la segunda vuelve a intentar, ve que la solicitud está aprobada.
            with self.assertRaises(UserError) as error:
                env_second["payment.request"].browse(request_id)._reject("Falta la factura")
            self.assertIn("aprobada", str(error.exception))
            second.rollback()
        with db.cursor() as cr:
            cr.execute("SELECT state, reject_reason FROM payment_request WHERE id = %s", [request_id])
            self.assertEqual(cr.fetchone(), ("approved", None))

    def test_a_record_pointing_to_the_request_does_not_block_it(self):
        """Crear un registro que apunta a la solicitud (por ejemplo, abrir el asistente de pago) no choca con el bloqueo.

        Al revisar esa clave foránea, PostgreSQL toma FOR KEY SHARE sobre la fila de la solicitud.
        """
        request_id = self._committed_request()
        db = sql_db.db_connect(get_db_name())
        with db.cursor() as first, db.cursor() as second:
            first.execute("SELECT id FROM payment_request WHERE id = %s FOR KEY SHARE", [request_id])
            second.execute(SET_LOCK_TIMEOUT)
            api.Environment(second, SUPERUSER_ID, {})["payment.request"].browse(request_id)._lock_for_update()
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
