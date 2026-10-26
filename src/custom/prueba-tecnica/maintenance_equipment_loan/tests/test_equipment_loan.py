from datetime import timedelta
from unittest.mock import patch

from psycopg2.errors import UniqueViolation

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestEquipmentLoan(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Usuario interno sin grupos de Mantenimiento: no sigue el equipo.
        cls.user = new_test_user(cls.env, login="loan_user", groups="base.group_user")
        cls.equipment = cls.env["maintenance.equipment"].create({"name": "Proyector de prueba"})
        cls.Loan = cls.env["equipment.loan"].with_user(cls.user)
        cls.today = fields.Date.context_today(cls.Loan)

    def _new_loan(self, days=7):
        return self.Loan.create(
            {
                "equipment_id": self.equipment.id,
                "date_expected_return": self.today + timedelta(days=days),
            }
        )

    def test_c2_full_flow_as_internal_user(self):
        """C2: borrador → prestado → devuelto, con los valores por defecto."""
        loan = self._new_loan()
        self.assertEqual(loan.user_id, self.user)
        self.assertEqual(loan.date_delivery, self.today)
        self.assertEqual(loan.state, "draft")
        loan.action_deliver()
        self.assertEqual(loan.state, "loaned")
        self.assertFalse(loan.date_returned)
        loan.action_return()
        self.assertEqual(loan.state, "returned")
        self.assertEqual(loan.date_returned, self.today)

    def test_c3_expected_return_before_delivery_is_blocked(self):
        """C3: la devolución prevista anterior a la entrega se bloquea con un mensaje claro."""
        with self.assertRaisesRegex(ValidationError, "no puede ser anterior a la fecha de entrega"):
            self._new_loan(days=-1)
        loan = self._new_loan()
        with self.assertRaisesRegex(ValidationError, "no puede ser anterior a la fecha de entrega"):
            loan.date_delivery = self.today + timedelta(days=30)

    def test_c3_same_day_return_is_allowed(self):
        """C3: devolver el mismo día de la entrega no es «anterior»."""
        self.assertEqual(self._new_loan(days=0).state, "draft")

    def test_c5_cannot_return_a_draft_loan(self):
        """C5: no se puede devolver un préstamo que sigue en borrador."""
        loan = self._new_loan()
        with self.assertRaises(UserError):
            loan.action_return()
        self.assertEqual(loan.state, "draft")
        self.assertFalse(loan.date_returned)

    def test_c4_each_action_only_in_its_state(self):
        """C4: cada acción se rechaza fuera de su estado, aunque se llame por código."""
        loan = self._new_loan()
        loan.action_deliver()
        with self.assertRaises(UserError):
            loan.action_deliver()
        with self.assertRaises(UserError):
            loan.action_cancel()
        loan.action_return()
        with self.assertRaises(UserError):
            loan.action_return()

    def test_c7_cancel_only_a_draft_loan(self):
        """C7 (propuesto): un borrador se cancela y queda como estado final."""
        loan = self._new_loan()
        loan.action_cancel()
        self.assertEqual(loan.state, "cancelled")
        with self.assertRaises(UserError):
            loan.action_deliver()

    def test_c6_delete_only_a_draft_loan(self):
        """C6 (propuesto): un borrador se elimina; uno entregado no."""
        draft = self._new_loan()
        draft.unlink()
        self.assertFalse(draft.exists())
        loaned = self._new_loan()
        loaned.action_deliver()
        with self.assertRaises(UserError):
            loaned.unlink()

    def test_internal_user_reads_equipment_not_followed(self):
        """Regla nueva: el usuario interno ve todos los equipos para poder prestarlos."""
        found = self.env["maintenance.equipment"].with_user(self.user).search([("id", "=", self.equipment.id)])
        self.assertEqual(found, self.equipment)

    def test_internal_user_still_cannot_edit_equipment(self):
        """Lo estándar sigue igual: el usuario interno no modifica equipos."""
        with self.assertRaises(AccessError):
            self.equipment.with_user(self.user).write({"name": "Cambiado"})

    # Tramo B

    def _loan_with_dates(self, delivery_days, expected_days):
        return self.Loan.create(
            {
                "equipment_id": self.equipment.id,
                "date_delivery": self.today + timedelta(days=delivery_days),
                "date_expected_return": self.today + timedelta(days=expected_days),
            }
        )

    def test_c8_cannot_deliver_equipment_already_loaned(self):
        """C8: un equipo prestado no se entrega a otra persona; el borrador sí se crea."""
        self._new_loan().action_deliver()
        second = self._new_loan()
        with self.assertRaisesRegex(ValidationError, "ya está prestado"):
            second.action_deliver()
        self.assertEqual(second.state, "draft")

    def test_c8_can_deliver_again_after_return(self):
        """C8: devuelto el equipo, se puede prestar de nuevo."""
        first = self._new_loan()
        first.action_deliver()
        first.action_return()
        second = self._new_loan()
        second.action_deliver()
        self.assertEqual(second.state, "loaned")

    def test_c9_database_rejects_two_loaned_loans(self):
        """C9: aunque se salte la comprobación en Python, la base de datos lo impide."""
        self._new_loan().action_deliver()
        second = self._new_loan()
        with mute_logger("odoo.sql_db"), self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            second.write({"state": "loaned"})
            second.flush_recordset()

    def test_c9_simultaneous_delivery_gets_a_clear_message(self):
        """C9: si otro usuario entrega el mismo equipo justo antes, el aviso es claro."""
        self._new_loan().action_deliver()
        second = self._new_loan()
        # Simula la carrera: la comprobación en Python todavía no ve la otra entrega.
        loan_class = type(self.env["equipment.loan"])
        with patch.object(loan_class, "_check_equipment_available", lambda self: None), mute_logger(
            "odoo.sql_db"
        ), self.assertRaisesRegex(ValidationError, "acaba de entregar"):
            second.action_deliver()

    def test_c9_update_stops_when_duplicates_exist(self):
        """C9 (decisión): con dos préstamos «Prestado» del mismo equipo, init() para y no toca datos."""
        self.env.cr.execute("DROP INDEX equipment_loan_one_loaned_per_equipment")
        loans = self._new_loan() | self._new_loan()
        loans.write({"state": "loaned"})
        loans.flush_recordset()
        with self.assertRaisesRegex(UserError, "Proyector de prueba"):
            self.env["equipment.loan"].init()
        self.assertEqual(set(loans.mapped("state")), {"loaned"})

    def test_c10_overdue_loan_is_flagged_and_filtered(self):
        """C10: prestado y con la devolución prevista ya pasada → vencido, y el filtro lo encuentra."""
        loan = self._loan_with_dates(delivery_days=-10, expected_days=-1)
        loan.action_deliver()
        self.assertTrue(loan.is_overdue)
        self.assertIn(loan, self.Loan.search([("is_overdue", "=", True)]))
        self.assertNotIn(loan, self.Loan.search([("is_overdue", "=", False)]))

    def test_c11_not_overdue_cases(self):
        """C11: no son vencidos el borrador, el devuelto ni el que vence hoy."""
        draft = self._loan_with_dates(delivery_days=-10, expected_days=-1)
        returned = self._loan_with_dates(delivery_days=-10, expected_days=-1)
        returned.action_deliver()
        returned.action_return()
        due_today = self._loan_with_dates(delivery_days=-3, expected_days=0)
        due_today.action_deliver()
        loans = draft | returned | due_today
        self.assertFalse(any(loans.mapped("is_overdue")))
        self.assertFalse(loans & self.Loan.search([("is_overdue", "=", True)]))
        self.assertEqual(loans, loans & self.Loan.search([("is_overdue", "!=", True)]))
