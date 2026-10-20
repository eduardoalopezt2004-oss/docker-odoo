import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

CODE_RE = re.compile(r"[A-Z0-9]{1,5}")


class ResCompany(models.Model):
    _inherit = "res.company"

    payment_request_code = fields.Char(
        string="Código para solicitudes de pago",
        help="Con código, la compañía numera sus solicitudes con su propio contador (DA/SP/2026/0001). "
        "Sin código, usa el contador general (SP/2026/0001). Cambiarlo solo afecta a las solicitudes nuevas.",
    )

    @api.constrains("payment_request_code")
    def _check_payment_request_code(self):
        for company in self.filtered("payment_request_code"):
            if not CODE_RE.fullmatch(company.payment_request_code):
                raise ValidationError(
                    _("El código para solicitudes de pago debe tener de 1 a 5 letras mayúsculas o números, sin espacios.")
                )
            # sudo(): la comparación es con todas las compañías, también las que este usuario no ve.
            duplicate = self.sudo().search(
                [("payment_request_code", "=", company.payment_request_code), ("id", "!=", company.id)], limit=1
            )
            if duplicate:
                raise ValidationError(
                    _(
                        "El código %(code)s ya lo usa la compañía %(company)s.",
                        code=company.payment_request_code,
                        company=duplicate.name,
                    )
                )
