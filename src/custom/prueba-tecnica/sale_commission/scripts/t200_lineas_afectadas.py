"""T-200: lista las líneas de pedido cuyo porcentaje de comisión no es el esperado.

SOLO LECTURA. Abre su propia transacción en modo de solo lectura antes de cualquier
consulta: si algo intentara escribir, PostgreSQL lo rechaza. No usa write, create ni unlink.

Uso (odoo shell lee el script por la entrada estándar):

    T200_DESDE="2026-10-16 16:00:00" T200_CSV=/tmp/t200_lineas_afectadas.csv \\
        odoo shell -d <base> --no-http < t200_lineas_afectadas.py

- T200_DESDE: fecha y hora en UTC desde la que se revisan pedidos confirmados
  (el despliegue de la versión 1.1.0). Se compara con date_order, que Odoo fija al confirmar.
- T200_CSV: archivo de salida. Por defecto /tmp/t200_lineas_afectadas.csv.

Porcentaje esperado: el de la regla de la categoría más específica del producto (de la
compañía de la línea o sin compañía) y, si no hay regla, el del vendedor del pedido
(order_id.user_id). No llama a _get_commission_percent(), que usa al usuario que confirma.
Usa las reglas y los porcentajes vigentes al momento de correr el script.
"""
# pylint: disable=print-used
# Script de operador para odoo shell: lo que imprime es el informe para quien lo corre.
import csv
import os
from collections import defaultdict

from odoo import SUPERUSER_ID, api, fields
from odoo.tools import float_compare, float_round

DESDE = fields.Datetime.to_datetime(os.environ["T200_DESDE"])
SALIDA = os.environ.get("T200_CSV", "/tmp/t200_lineas_afectadas.csv")
COLUMNAS = [
    "pedido", "linea_id", "compania", "vendedor", "confirmo", "fecha_confirmacion",
    "producto", "categoria", "origen_esperado", "porcentaje_guardado", "porcentaje_esperado",
    "comision_guardada", "comision_esperada", "diferencia", "moneda",
]

with env.registry.cursor() as cr:  # noqa: F821 (env lo define odoo shell)
    cr.execute("SET TRANSACTION READ ONLY")
    cr.execute("SHOW transaction_read_only")
    if cr.fetchone()[0] != "on":
        raise SystemExit("La transacción no quedó en solo lectura; no se continúa.")
    try:
        ro_env = api.Environment(cr, SUPERUSER_ID, {})
        Order = ro_env["sale.order"]

        # El chatter guarda la etiqueta del estado en el idioma de quien confirmó.
        sale_labels = set()
        for code in ro_env["res.lang"].search([]).mapped("code"):
            selection = Order._fields["state"]._description_selection(ro_env(context={"lang": code}))
            sale_labels.add(dict(selection)["sale"])

        rules = ro_env["sale.commission.rule"].search([])
        rule_cache = {}

        def expected_rule(categ, company):
            key = (categ.id, company.id)
            if key not in rule_cache:
                chain = {int(x) for x in (categ.parent_path or "").split("/") if x}
                candidates = rules.filtered(
                    lambda r: r.categ_id.id in chain and r.company_id in (company, ro_env["res.company"])
                )
                best = candidates.sorted(lambda r: len(r.categ_id.parent_path or ""), reverse=True)[:1]
                rule_cache[key] = best
            return rule_cache[key]

        def confirmed_by(order):
            tracking = ro_env["mail.tracking.value"].search([
                ("mail_message_id.model", "=", "sale.order"),
                ("mail_message_id.res_id", "=", order.id),
                ("field_id.name", "=", "state"),
                ("new_value_char", "in", list(sale_labels)),
            ], order="id desc", limit=1)
            return tracking.mail_message_id.author_id.name or "(sin registro en el chatter)"

        lines = ro_env["sale.order.line"].search([
            ("order_id.state", "=", "sale"),
            ("order_id.date_order", ">=", DESDE),
            ("display_type", "=", False),
        ], order="order_id, id")

        rows = []
        totals = defaultdict(float)
        for line in lines:
            order = line.order_id
            rule = expected_rule(line.product_id.categ_id, line.company_id)
            expected = rule.percent if rule else order.user_id.commission_percent
            if not float_compare(line.commission_percent, expected, precision_digits=2):
                continue
            rounding = line.currency_id.rounding
            expected_amount = float_round(line.price_subtotal * expected / 100.0, precision_rounding=rounding)
            diff = float_round(expected_amount - line.commission_amount, precision_rounding=rounding)
            totals[line.currency_id.name] += diff
            rows.append({
                "pedido": order.name,
                "linea_id": line.id,
                "compania": line.company_id.name,
                "vendedor": order.user_id.login,
                "confirmo": confirmed_by(order),
                "fecha_confirmacion": fields.Datetime.to_string(order.date_order),
                "producto": line.product_id.display_name,
                "categoria": line.product_id.categ_id.complete_name,
                "origen_esperado": "regla: %s" % rule.categ_id.complete_name if rule else "vendedor del pedido",
                "porcentaje_guardado": "%.2f" % line.commission_percent,
                "porcentaje_esperado": "%.2f" % expected,
                "comision_guardada": "%.2f" % line.commission_amount,
                "comision_esperada": "%.2f" % expected_amount,
                "diferencia": "%.2f" % diff,
                "moneda": line.currency_id.name,
            })

        with open(SALIDA, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNAS)
            writer.writeheader()
            writer.writerows(rows)

        print("T200 líneas revisadas: %s" % len(lines))
        print("T200 líneas con porcentaje distinto al esperado: %s" % len(rows))
        for currency, total in sorted(totals.items()):
            print("T200 diferencia total %s: %.2f" % (currency, total))
        print("T200 archivo: %s" % SALIDA)
    finally:
        cr.rollback()
