# Incidente T-200: los vendedores no pueden confirmar pedidos

- Cliente: Comercial Los Andes C.A. (ficticia).
- Reportado: viernes, 5:40 p.m.
- Inicio: despliegue de las 12:00 m. (commit `3f4d73f`, versión 1.1.0).
- Severidad: crítica. Ningún vendedor puede confirmar pedidos; solo el gerente.
- Corrección: rama `hotfix/T-200`, versión 1.1.1.

## Cómo se reproduce

Con el código de producción (`87ac54d`, versión 1.1.0):

1. Entrar con un usuario que tenga el grupo de vendedor (`sales_team.group_sale_salesman`) y no el de gerente.
2. Crear un pedido de venta con cualquier producto. No hace falta que haya reglas de comisión creadas.
3. Pulsar *Confirmar*.
4. Odoo muestra este error y el pedido sigue como cotización:

```text
You are not allowed to access 'Comisión por categoría de producto' (sale.commission.rule) records.

This operation is allowed for the following groups:
	- Sales/Administrator

Contact your administrator to request access if necessary.
```

Con el usuario del gerente, el mismo pedido se confirma.

Se reprodujo el 2026-10-18 de dos maneras: confirmando como el vendedor desde `odoo shell`, en una base con un vendedor, un gerente y una categoría con regla del 8 %; y con las pruebas automáticas de la sección *Prueba*.

## Causa raíz

El commit `3f4d73f` ("porcentaje de comisión por categoría de producto") hizo dos cambios que juntos producen el error:

- Creó el modelo `sale.commission.rule` con acceso solo para el gerente (`security/ir.model.access.csv`).
- Hizo que `action_confirm` llame a `_get_commission_percent()`, que busca en ese modelo con el usuario que confirma (`models/sale_order_line.py`).

Odoo revisa el permiso sobre el modelo antes de buscar. Si confirma un vendedor, la búsqueda lanza `AccessError`, la transacción se deshace y el pedido no se confirma. El gerente tiene acceso al modelo y por eso a él le funciona. El error no depende de los datos: ocurre aunque no exista ninguna regla.

Cómo se identificó el commit: `git log --oneline -- src/custom/prueba-tecnica/sale_commission` muestra tres commits. Solo `3f4d73f` toca `ir.model.access.csv` y `action_confirm`; `ad51040` (1.0) no tenía el modelo `sale.commission.rule` y `87ac54d` solo cambia el README. Las pruebas nuevas, aplicadas sobre `87ac54d`, fallan con el `AccessError`.

## Por qué pasó la revisión

En el mismo commit, `_create_order` de las pruebas dejó de usar `with_user(user)`. Desde entonces todas las pruebas crean y confirman los pedidos como superusuario, que no pasa por los permisos. Las 4 pruebas pasaban con el error presente.

También se agregó `cls.env.user.commission_percent = 5.0`. Esa línea iguala el porcentaje del superusuario con el del vendedor y oculta el hallazgo 1.

## Corrección

Commit `6cf69c3`. Una línea en `models/sale_order_line.py`, con su comentario:

```python
rules = self.env["sale.commission.rule"].sudo().search([...])
```

Por qué `sudo()` y no darle al vendedor permiso de lectura sobre el modelo:

- Las reglas son configuración del gerente. El campo *Comisión (%)* de la categoría ya está limitado al grupo del gerente. Con permiso de lectura, cualquier vendedor podría listar todas las reglas por RPC.
- `sudo()` solo afecta esta búsqueda. El dominio la limita a la categoría del producto (y sus categorías padre) y a la compañía de la línea, y del resultado solo se usa el porcentaje.
- El modelo no tiene reglas de registro, así que `sudo()` no se salta ningún filtro. El filtro por compañía ya está en el dominio.
- `self.env.user` no cambia: el porcentaje de respaldo sale del mismo usuario que antes de la corrección.

El cálculo no cambia. La versión sube de 1.1.0 a 1.1.1 para que la actualización del módulo quede registrada.

## Prueba

Commit `ef377bf`, en `tests/test_sale_commission.py`. Cada prueba confirma con el usuario indicado mediante `with_user()`:

| Prueba | Usuario | Qué comprueba |
|---|---|---|
| `test_salesman_confirms_order_with_category_rule` | vendedor | Confirma y la línea toma el 8 % de su categoría |
| `test_salesman_confirms_order_without_rule` | vendedor | Confirma sin reglas y toma su propio 5 % |
| `test_manager_confirms_order_with_category_rule` | gerente | Sigue confirmando igual que antes |
| `test_salesman_cannot_read_rules` | vendedor | Sigue sin poder leer las reglas (`AccessError`) |

Resultado, cada vez en una base nueva:

- Solo con las pruebas (`ef377bf`, sin la corrección): `0 failed, 2 error(s) of 8 tests`. Los dos errores son el `AccessError` de arriba, en las dos pruebas del vendedor.
- Con la corrección (`6cf69c3`): `0 failed, 0 error(s) of 8 tests`.

Comando:

```bash
./odoo test -i prueba-tecnica -d <base_nueva> -m sale_commission
```

El comando termina con código 0 aunque haya pruebas con error. Hay que leer la línea `... of N tests` del final.

## Contención (primeros 15 minutos)

Objetivo: que los vendedores puedan confirmar el sábado a las 8:00 a.m. aunque la corrección todavía no esté desplegada. No requiere desplegar código.

1. Minuto 0 a 2. Pedirle al gerente que deje de confirmar pedidos de otros vendedores. Por el hallazgo 1, cada pedido que confirma por otro queda con su porcentaje cuando la categoría no tiene regla. Pedirle también la lista de los que ya confirmó.
2. Minuto 2 a 8. Con un usuario administrador, activar el modo desarrollador (agregar `?debug=1` a la dirección, por ejemplo `/odoo?debug=1`) y crear un permiso temporal en *Ajustes › Técnico › Seguridad › Permisos de acceso › Nuevo*:
   - Nombre: `TEMPORAL T-200 vendedor lee reglas`.
   - Modelo: *Comisión por categoría de producto* (`sale.commission.rule`).
   - Grupo: *Ventas / Usuario: solo mostrar documentos propios* (`sales_team.group_sale_salesman`).
   - Marcar solo *Leer*. Dejar sin marcar escribir, crear y eliminar.
3. Minuto 8 a 12. Entrar como un vendedor y confirmar un pedido. Debe confirmarse.
4. Minuto 12 a 15. Avisar al cliente que ya pueden vender y que no usen el botón *Recalcular comisiones* hasta nuevo aviso.

Esta es la misma exposición que se descartó para la corrección: con el permiso, cualquier vendedor puede leer todas las reglas de comisión. Se acepta solo como medida temporal por cuatro razones:

- Es de solo lectura: el vendedor ve porcentajes por categoría, pero no los cambia.
- Se activa en minutos sin desplegar código un viernes a las 5:40 p.m.
- Se revierte borrando un registro.
- Las alternativas son peores: no vender el sábado, o que el gerente siga confirmando y dejando comisiones equivocadas.

Riesgos:

- Mientras exista el permiso, los vendedores pueden ver los porcentajes por categoría.
- La actualización del módulo no borra el permiso, porque es un registro creado a mano. Si nadie lo borra, la exposición queda para siempre. Por eso borrarlo es un paso del despliegue.
- Con el permiso, el vendedor también puede usar *Recalcular comisiones*, que aplica reglas distintas (hallazgo 2). Comprobado: en un producto de una subcategoría sin regla propia, la confirmación pone el 8 % de la categoría padre y el botón lo baja a 5 %. Por eso el aviso del paso 4.

Comprobado el 2026-10-18 con el código 1.1.0 en `odoo shell`, deshaciendo todo al final: sin el permiso el vendedor recibe `AccessError`, con el permiso confirma con 8 % y, al borrarlo, vuelve el error.

## Despliegue y verificación

La corrección no cambia la estructura de la base. Solo cambia código Python y la versión del módulo.

1. Respaldo de la base y del filestore:

   ```bash
   pg_dump -Fc -f respaldo_antes_T200.dump <base>
   tar czf filestore_antes_T200.tgz -C <data_dir>/filestore <base>
   pg_restore -l respaldo_antes_T200.dump | head    # comprueba que el respaldo se puede leer
   ```

2. Poner en el servidor el código de la rama `hotfix/T-200`.
3. Actualizar solo el módulo `sale_commission` y reiniciar Odoo:

   ```bash
   odoo -d <base> -u sale_commission --stop-after-init
   # con el CLI de este repositorio:
   ./odoo update <instancia> -d <base> -m sale_commission
   ```

4. Verificar, en este orden:
   1. En *Aplicaciones*, *Comisiones de vendedores* muestra la versión `18.0.1.1.1`.
   2. Borrar el permiso `TEMPORAL T-200 vendedor lee reglas` (modo desarrollador, *Ajustes › Técnico › Seguridad › Permisos de acceso*, buscar "TEMPORAL").
   3. Un vendedor confirma un pedido propio. Debe confirmarse sin el permiso temporal: eso prueba que funciona la corrección, no la contención.
   4. El gerente confirma un pedido propio igual que antes.
   5. En *Ventas › Reportes › Comisiones*, los dos pedidos aparecen con su comisión. En el pedido no se ve la columna por el hallazgo 4.
   6. El registro de Odoo no tiene `ERROR` ni `AccessError` desde el reinicio.
5. Avisar al cliente que pueden volver a usar el sistema normalmente. El botón *Recalcular comisiones* sigue sin usarse hasta resolver el hallazgo 2.

Si algo falla: volver a poner el código anterior y reiniciar. Como la base no cambia de estructura, no hace falta restaurar el respaldo. Luego se vuelve a crear el permiso temporal.

Probado en la base local: `odoo -u sale_commission` sube la versión a `18.0.1.1.1` y el vendedor confirma. `./odoo update prueba-tecnica -d prueba_t200 -m sale_commission` ejecuta ese mismo comando.

## Impacto en los datos

Hay dos efectos:

- Los pedidos que los vendedores intentaron confirmar desde las 12:00 m. siguen como cotización. El error deshizo la transacción, así que no quedaron datos a medias. Hay que confirmarlos después del despliegue.
- Los pedidos que el gerente confirmó por otros vendedores tienen el porcentaje del gerente en las líneas sin regla de categoría (hallazgo 1).

### Script de solo lectura

`scripts/t200_lineas_afectadas.py` lista las líneas confirmadas desde una fecha cuyo porcentaje no es el esperado. Abre una transacción de solo lectura antes de cualquier consulta, y PostgreSQL rechaza cualquier escritura. Saca un CSV con pedido, línea, vendedor, quién confirmó (según el chatter), porcentaje y comisión guardados y esperados, y la diferencia.

Porcentaje esperado: el de la regla de la categoría más específica y, si no hay, el del vendedor del pedido (`order_id.user_id`). No usa `_get_commission_percent()`, que tiene el error del hallazgo 1. Supuesto: se usan las reglas y porcentajes vigentes al correr el script. Si alguien cambió una regla después del despliegue, esa línea aparece como diferencia y hay que revisarla a mano.

```bash
T200_DESDE="2026-10-16 16:00:00" T200_CSV=/tmp/t200_lineas_afectadas.csv \
    odoo shell -d <base> --no-http < scripts/t200_lineas_afectadas.py
```

`T200_DESDE` va en UTC. Supuesto: el cliente está en Venezuela (UTC-4), así que las 12:00 m. del viernes son las 16:00 UTC.

Probado en la base local con dos pedidos de un vendedor (5 %) confirmados por el gerente (4 %) con un producto sin regla, y uno de control con regla. El script lista solo los dos afectados (S00006 y S00008, 2,50 USD de diferencia) e identifica al gerente como quien confirmó S00008. S00006 sale "sin registro en el chatter" porque se creó y confirmó en la misma transacción; en uso normal son dos pasos distintos y el chatter lo registra. En una transacción abierta igual que la del script, un `UPDATE` falla con `cannot execute UPDATE in a read-only transaction`.

### Plan de corrección

Precondición: no corregir mientras siga abierta la causa del hallazgo 1. Si no, los pedidos que se confirmen después vuelven a quedar mal. Hasta entonces, el gerente no confirma pedidos de otros.

No se usa *Recalcular comisiones* para corregir: aplica reglas distintas a las de la confirmación (hallazgo 2).

1. Respaldo de la base, como en el paso 1 del despliegue.
2. Correr `scripts/t200_lineas_afectadas.py` con la hora del despliegue de la 1.1.0.
3. Enviar el CSV al gerente de ventas del cliente. Las comisiones son dinero: él aprueba cada fila o la borra del CSV.
4. Simular la corrección con el CSV aprobado. No guarda nada:

   ```bash
   T200_CSV=/tmp/t200_lineas_afectadas.csv odoo shell -d <base> --no-http < scripts/t200_corregir_lineas.py
   ```

   Revisar que `corregida` sea igual al número de filas y que `cambio_desde_el_listado` sea 0. Si no es 0, alguien cambió esas líneas después del listado: se revisan a mano y se quitan del CSV.
5. Aplicar:

   ```bash
   T200_APLICAR=1 T200_CSV=/tmp/t200_lineas_afectadas.csv odoo shell -d <base> --no-http < scripts/t200_corregir_lineas.py
   ```

   El script escribe el porcentaje esperado, la comisión se recalcula sola y deja una nota en el chatter de cada pedido. Confirma la transacción cada 200 líneas (`T200_LOTE`).
6. Verificar: volver a correr el script de solo lectura con la misma fecha. Debe dar 0 líneas. Un pedido corregido tiene la nota "T-200: comisión de la línea ... corregida de ... a ...".
7. Si hay que deshacer: restaurar el respaldo del paso 1. Por eso conviene correr los pasos 1 a 6 seguidos y fuera del horario de ventas.

Probado en la base local, con respaldo antes y restauración al final:

- La simulación no cambió nada: la detección siguió dando 2 líneas.
- Una fila cuyo porcentaje cambió desde el listado se informó y no se tocó.
- Al aplicar se corrigieron las 2 líneas (4 % a 5 %; comisión de 4,00 a 5,00 y de 6,00 a 7,50).
- La detección dio 0 líneas.
- Aplicar otra vez con el mismo CSV no cambió nada (`ya_corregida: 2`) ni duplicó las notas.
- La restauración del respaldo devolvió las 2 líneas afectadas.

## Hallazgos fuera de esta corrección

No entran en el hotfix porque cambian la lógica de cálculo o no son la causa del ticket. Quedan como propuestas. Los cuatro se comprobaron el 2026-10-18 en la base local.

1. El porcentaje de respaldo es el de quien confirma, no el del vendedor del pedido. Hasta la 1.0 salía de `order.user_id.commission_percent`; desde `3f4d73f` sale de `self.env.user.commission_percent`. Si el gerente (4 %) confirma el pedido de un vendedor (5 %) y la categoría no tiene regla, la línea queda con 4 %. Según el ticket, esta tarde el gerente confirmó los pedidos de todos, así que esos pedidos pueden tener la comisión equivocada. Propuesta: en un ticket aparte, volver a `self.order_id.user_id.commission_percent`, con su prueba, y revisar los pedidos confirmados desde las 12:00 m.
2. El botón *Recalcular comisiones* también falla para el vendedor con el mismo `AccessError`, porque busca en el mismo modelo. Además aplica reglas distintas a las de la confirmación: solo compara la categoría exacta (sin categorías padre) y no filtra por compañía. Propuesta: decidir si el vendedor debe poder recalcular. Si no, mostrar el botón solo al gerente y comprobar el grupo dentro del método. En los dos casos, que use `_get_commission_percent()`.
3. Cualquier usuario interno puede leer el porcentaje de comisión de los demás. El campo `res.users.commission_percent` no tiene `groups=`; un vendedor lee el porcentaje del gerente. Viene de la versión 1.0. Propuesta: limitar el campo al grupo del gerente, comprobando antes que el cálculo no lo lea con el usuario del vendedor.
4. Las columnas *Comisión* y *Comisión (%)* no aparecen en las líneas del pedido. La vista usa `//field[@name='order_line']//field[@name='price_subtotal']`, y en Odoo 18 el primer `price_subtotal` dentro de `order_line` es el campo invisible del formulario de la línea, no el de la lista. Los dos campos quedan en ese formulario. Viene de la versión 1.0. Propuesta: anclar el xpath a la lista, `//field[@name='order_line']/list//field[@name='price_subtotal']`.

Búsqueda del mismo patrón: se revisó cada lugar del módulo que lee `sale.commission.rule` con el usuario actual. Son `_get_commission_percent()` (la causa de T-200), `action_recompute_commissions()` (hallazgo 2) y el campo *Comisión (%)* de la categoría. Este último no falla, porque tiene `groups="sales_team.group_sale_manager"` y solo lo calcula el gerente. También se revisó qué lee el vendedor al confirmar: `res.users.commission_percent` no falla, pero lo expone (hallazgo 3).

## Prevención

- Prueba: cada acción que usa un vendedor se prueba con `with_user()` y el grupo más bajo que la usa. Las cuatro pruebas de T-200 lo hacen para `action_confirm`. Falta hacerlo para `action_recompute_commissions`, cuando se decida el hallazgo 2.
- Regla de revisión: si un commit crea un modelo con acceso solo para un grupo, el revisor busca dónde se lee ese modelo (`grep -rn "sale.commission.rule"`) y con qué usuario corre ese código.
- Regla de revisión: si un commit cambia una prueba existente para que siga pasando (quitar `with_user()`, igualar valores en el `setUpClass`), tiene que explicar por qué en el mensaje del commit. Eso es lo que ocultó T-200.
