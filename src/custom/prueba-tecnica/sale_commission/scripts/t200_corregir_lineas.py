"""T-200: corrige el porcentaje de comisión de las líneas listadas por t200_lineas_afectadas.py.

ESCRIBE EN LA BASE solo con T200_APLICAR=1. Sin esa variable simula y no guarda nada.

Precondiciones (ver el plan de corrección en INCIDENT.md):
- Respaldo de la base hecho y verificado.
- La corrección del hallazgo 1 ya está desplegada. Si no, los pedidos que se confirmen
  después siguen quedando mal y habría que repetir todo.
- El CSV fue revisado y aprobado por el cliente. Las filas que no se deban corregir se borran
  del CSV antes de correr este script.

Uso:

    T200_CSV=/tmp/t200_lineas_afectadas.csv odoo shell -d <base> --no-http < t200_corregir_lineas.py
    T200_APLICAR=1 T200_CSV=/tmp/t200_lineas_afectadas.csv odoo shell -d <base> --no-http < t200_corregir_lineas.py

Para cada fila:
- Si la línea ya tiene el porcentaje esperado, no se toca (correrlo dos veces no cambia nada).
- Si la línea tiene un porcentaje distinto al que había al generar el CSV, no se toca y se
  informa: alguien la cambió después y hay que revisarla a mano.
- Si no, se escribe el porcentaje esperado. La comisión se recalcula sola y se deja una nota
  en el chatter del pedido.

No usa el botón "Recalcular comisiones" (hallazgo 2). Confirma la transacción cada T200_LOTE
líneas (por defecto 200). Antes de escribir valida todas las filas; si una tiene un error, no
corrige nada.

Acepta el CSV tal como lo genera t200_lineas_afectadas.py o como lo guarda Excel en español:
separador ',' o ';', punto o coma decimal, UTF-8 o cp1252.
"""
# pylint: disable=print-used
# Script de operador para odoo shell: lo que imprime es el informe para quien lo corre.
import csv
import io
import os

from odoo.tools import float_compare

ARCHIVO = os.environ.get("T200_CSV", "/tmp/t200_lineas_afectadas.csv")
APLICAR = os.environ.get("T200_APLICAR") == "1"
LOTE = int(os.environ.get("T200_LOTE", "200"))


def read_csv(path):
    """Lee el CSV tal como lo genera t200_lineas_afectadas.py o como lo guarda Excel en español
    (separador ';', coma decimal, cp1252)."""
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    header = text.splitlines()[0] if text.strip() else ""
    delimiter = ";" if header.count(";") > header.count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


def to_percent(value):
    number = float(value.strip().replace(",", "."))
    if not 0 <= number <= 100:
        raise ValueError("%s no está entre 0 y 100" % value)
    return number


# Se valida todo el CSV antes de escribir nada: un error a mitad de camino no deja la corrección
# aplicada a medias.
rows, errors = [], []
for number, row in enumerate(read_csv(ARCHIVO), start=2):
    try:
        rows.append((int(row["linea_id"]), to_percent(row["porcentaje_guardado"]),
                     to_percent(row["porcentaje_esperado"])))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        errors.append("fila %s: %s" % (number, exc))
if errors:
    for error in errors:
        print("T200 error en el CSV, %s" % error)
    raise SystemExit("T200 el CSV tiene errores; no se corrigió nada.")

Line = env["sale.order.line"]  # noqa: F821 (env lo define odoo shell)
result = {"corregida": 0, "ya_corregida": 0, "cambio_desde_el_listado": 0, "no_existe": 0}
pending = 0

for line_id, stored, expected in rows:
    line = Line.browse(line_id).exists()
    if not line:
        result["no_existe"] += 1
        print("T200 línea %s: no existe" % line_id)
        continue
    if not float_compare(line.commission_percent, expected, precision_digits=2):
        result["ya_corregida"] += 1
        continue
    if float_compare(line.commission_percent, stored, precision_digits=2):
        result["cambio_desde_el_listado"] += 1
        print("T200 línea %s (%s): tiene %.2f %% y el listado decía %.2f %%; no se toca"
              % (line.id, line.order_id.name, line.commission_percent, stored))
        continue
    result["corregida"] += 1
    print("T200 línea %s (%s): %.2f %% -> %.2f %%%s"
          % (line.id, line.order_id.name, stored, expected, "" if APLICAR else " (simulado)"))
    if not APLICAR:
        continue
    old_amount = line.commission_amount
    line.commission_percent = expected
    line.order_id.message_post(
        body=env._(  # noqa: F821
            "T-200: comisión de la línea «%(product)s» corregida de %(old_pct).2f %% (%(old_amount).2f) "
            "a %(new_pct).2f %% (%(new_amount).2f).",
            product=line.product_id.display_name, old_pct=stored, old_amount=old_amount,
            new_pct=expected, new_amount=line.commission_amount,
        ),
        subtype_xmlid="mail.mt_note",
    )
    pending += 1
    if pending >= LOTE:
        env.cr.commit()  # noqa: F821
        pending = 0

if APLICAR:
    env.cr.commit()  # noqa: F821
else:
    env.cr.rollback()  # noqa: F821

print("T200 modo: %s" % ("APLICADO" if APLICAR else "SIMULACIÓN, no se guardó nada"))
for key, value in result.items():
    print("T200 %s: %s" % (key, value))
