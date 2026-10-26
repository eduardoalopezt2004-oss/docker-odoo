from psycopg2.errors import UniqueViolation

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date

ONE_LOANED_INDEX = "equipment_loan_one_loaned_per_equipment"


class EquipmentLoan(models.Model):
    _name = "equipment.loan"
    _description = "Préstamo de equipo"
    _order = "date_delivery desc, id desc"

    equipment_id = fields.Many2one(
        "maintenance.equipment", string="Equipo", required=True, ondelete="restrict"
    )
    user_id = fields.Many2one(
        "res.users", string="Recibe", required=True, default=lambda self: self.env.user
    )
    date_delivery = fields.Date(
        string="Fecha de entrega", required=True, default=fields.Date.context_today
    )
    date_expected_return = fields.Date(string="Devolución prevista", required=True)
    date_returned = fields.Date(string="Devolución real", readonly=True, copy=False)
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("loaned", "Prestado"),
            ("returned", "Devuelto"),
            ("cancelled", "Cancelado"),
        ],
        string="Estado",
        default="draft",
        required=True,
        readonly=True,
        copy=False,
    )
    # Depende de la fecha de hoy: no se guarda, para que nunca quede viejo.
    is_overdue = fields.Boolean(
        string="Vencido", compute="_compute_is_overdue", search="_search_is_overdue"
    )

    def init(self):
        # Un solo préstamo «Prestado» por equipo, garantizado por la base de datos:
        # cubre dos entregas simultáneas y las escrituras que no pasan por action_deliver.
        self.env.cr.execute(
            """
            SELECT equipment_id, array_agg(id ORDER BY id)
              FROM equipment_loan
             WHERE state = 'loaned'
             GROUP BY equipment_id
            HAVING count(*) > 1
            """
        )
        duplicates = self.env.cr.fetchall()
        if duplicates:
            detail = "; ".join(
                f"{self.env['maintenance.equipment'].browse(equipment_id).display_name}: {loan_ids}"
                for equipment_id, loan_ids in duplicates
            )
            raise UserError(
                _(
                    "No se puede activar la regla «un préstamo por equipo»: hay equipos con más de "
                    "un préstamo en estado Prestado (%(detail)s). Devuelva los que sobran y vuelva "
                    "a actualizar el módulo.",
                    detail=detail,
                )
            )
        # El nombre del índice es ONE_LOANED_INDEX.
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS equipment_loan_one_loaned_per_equipment
                ON equipment_loan (equipment_id) WHERE state = 'loaned'
            """
        )

    @api.depends("state", "date_expected_return")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for loan in self:
            loan.is_overdue = bool(
                loan.state == "loaned"
                and loan.date_expected_return
                and loan.date_expected_return < today
            )

    def _search_is_overdue(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise UserError(_("Solo se puede filtrar «Vencido» por sí o por no."))
        overdue = [
            "&",
            ("state", "=", "loaned"),
            ("date_expected_return", "<", fields.Date.context_today(self)),
        ]
        return overdue if (operator == "=") == value else ["!", *overdue]

    @api.depends("equipment_id", "user_id")
    def _compute_display_name(self):
        for loan in self:
            loan.display_name = f"{loan.equipment_id.display_name or ''} - {loan.user_id.display_name or ''}"

    @api.constrains("date_delivery", "date_expected_return")
    def _check_expected_return(self):
        for loan in self:
            if loan.date_expected_return < loan.date_delivery:
                raise ValidationError(
                    _(
                        "La devolución prevista (%(expected)s) no puede ser anterior "
                        "a la fecha de entrega (%(delivery)s).",
                        expected=format_date(self.env, loan.date_expected_return),
                        delivery=format_date(self.env, loan.date_delivery),
                    )
                )

    def _check_state(self, allowed, message):
        # Un botón oculto no protege una llamada directa al método.
        if any(loan.state not in allowed for loan in self):
            raise UserError(message)

    def _check_equipment_available(self):
        # Solo para dar un mensaje claro; la garantía es el índice de init().
        for loan in self:
            active = self.search(
                [
                    ("equipment_id", "=", loan.equipment_id.id),
                    ("state", "=", "loaned"),
                    ("id", "!=", loan.id),
                ],
                limit=1,
            )
            if active:
                raise ValidationError(
                    _(
                        "«%(equipment)s» ya está prestado a %(user)s desde el %(date)s. "
                        "Debe devolverse antes de entregarlo otra vez.",
                        equipment=loan.equipment_id.display_name,
                        user=active.user_id.display_name,
                        date=format_date(self.env, active.date_delivery),
                    )
                )

    def action_deliver(self):
        self._check_state(("draft",), _("Solo se puede entregar un préstamo en borrador."))
        self._check_equipment_available()
        try:
            with self.env.cr.savepoint():
                self.write({"state": "loaned"})
                self.flush_recordset(["state"])
        except UniqueViolation as error:
            if error.diag.constraint_name != ONE_LOANED_INDEX:
                raise
            raise ValidationError(
                _(
                    "Otro usuario acaba de entregar este equipo. "
                    "Recargue la página para ver quién lo tiene."
                )
            ) from error

    def action_return(self):
        self._check_state(
            ("loaned",), _("Solo se puede devolver un préstamo que está prestado.")
        )
        self.write({"state": "returned", "date_returned": fields.Date.context_today(self)})

    def action_cancel(self):
        self._check_state(("draft",), _("Solo se puede cancelar un préstamo en borrador."))
        self.write({"state": "cancelled"})

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if any(loan.state != "draft" for loan in self):
            raise UserError(
                _("Solo se pueden eliminar préstamos en borrador. Uno entregado queda como registro.")
            )
