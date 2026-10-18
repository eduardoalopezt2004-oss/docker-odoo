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

## Hallazgos fuera de esta corrección

No entran en el hotfix porque cambian la lógica de cálculo o no son la causa del ticket. Quedan como propuestas. Los tres se comprobaron el 2026-10-18 en `odoo shell`, deshaciendo los cambios al final.

1. El porcentaje de respaldo es el de quien confirma, no el del vendedor del pedido. Hasta la 1.0 salía de `order.user_id.commission_percent`; desde `3f4d73f` sale de `self.env.user.commission_percent`. Si el gerente (4 %) confirma el pedido de un vendedor (5 %) y la categoría no tiene regla, la línea queda con 4 %. Según el ticket, esta tarde el gerente confirmó los pedidos de todos, así que esos pedidos pueden tener la comisión equivocada. Propuesta: en un ticket aparte, volver a `self.order_id.user_id.commission_percent`, con su prueba, y revisar los pedidos confirmados desde las 12:00 m.
2. El botón *Recalcular comisiones* también falla para el vendedor con el mismo `AccessError`, porque busca en el mismo modelo. Además aplica reglas distintas a las de la confirmación: solo compara la categoría exacta (sin categorías padre) y no filtra por compañía. Propuesta: decidir si el vendedor debe poder recalcular. Si no, mostrar el botón solo al gerente y comprobar el grupo dentro del método. En los dos casos, que use `_get_commission_percent()`.
3. Cualquier usuario interno puede leer el porcentaje de comisión de los demás. El campo `res.users.commission_percent` no tiene `groups=`; un vendedor lee el porcentaje del gerente. Viene de la versión 1.0. Propuesta: limitar el campo al grupo del gerente, comprobando antes que el cálculo no lo lea con el usuario del vendedor.
