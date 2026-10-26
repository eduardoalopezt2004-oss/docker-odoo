from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date


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

    def action_deliver(self):
        self._check_state(("draft",), _("Solo se puede entregar un préstamo en borrador."))
        self.write({"state": "loaned"})

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
