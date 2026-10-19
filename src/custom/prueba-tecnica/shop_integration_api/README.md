# API de productos para la tienda en línea (`shop_integration_api`)

Ejercicio 1 de la prueba técnica. La tienda en línea del cliente consulta en Odoo el catálogo que puede vender: código, nombre, precio y cantidad disponible de cada producto. Este documento está escrito para quien programa la integración del lado de la tienda.

## Tramos

- [x] A: `GET /api/v1/products` con sesión de usuario, filtros y errores claros.
- [ ] B: no iniciado.
- [ ] C: no iniciado.

## Conectarse

La API usa la sesión de un usuario de Odoo (`auth='user'`). Recomendamos un usuario solo para la tienda, con el tipo «Usuario interno» y sin grupos de Ventas ni de Inventario.

1. Abrir la sesión con `POST /web/session/authenticate` (JSON-RPC) y guardar la cookie `session_id` que devuelve:

   ```bash
   curl -s -c cookies.txt -H "Content-Type: application/json" \
     -d '{"jsonrpc": "2.0", "params": {"db": "<base>", "login": "<usuario>", "password": "<contraseña>"}}' \
     https://<servidor>/web/session/authenticate
   ```

2. Mandar esa cookie en cada consulta:

   ```bash
   curl -s -b cookies.txt "https://<servidor>/api/v1/products?in_stock=true"
   ```

La sesión vence por inactividad. Si una consulta responde 303 o 404 (ver [Errores](#errores)), hay que repetir el paso 1.

## `GET /api/v1/products`

Devuelve los productos activos que se pueden vender (casilla **Sales** de la ficha del producto, campo `sale_ok`). Cada variante es un producto. La lista va ordenada por `id`.

### Parámetros

Todos son opcionales. Si se mandan varios, el producto tiene que cumplirlos todos.

| Parámetro | Formato | Qué hace |
|---|---|---|
| `category_id` | Entero positivo: el id de la categoría | Productos de esa categoría y de sus subcategorías |
| `in_stock` | `true` o `false` | `true`: solo productos con cantidad disponible mayor que cero. `false`: lo mismo que no mandarlo |
| `modified_since` | `AAAA-MM-DD` o `AAAA-MM-DDTHH:MM:SS`, en UTC, con `Z` final opcional (`2026-10-19T14:30:00Z`) | Productos cuyo código, nombre o precio pudo cambiar en esa fecha y hora o después. Una fecha sola cuenta desde las 00:00:00 UTC |

No se aceptan otros parámetros, ni el mismo parámetro dos veces: responden 400.

### Respuesta

`200`, con `Content-Type: application/json`:

```json
{
  "count": 2,
  "products": [
    {"id": 11, "code": "TIENDA-001", "name": "Escritorio", "price": 150.0, "quantity": 8.0},
    {"id": 15, "code": null, "name": "Instalación", "price": 30.0, "quantity": 0.0}
  ]
}
```

| Campo | Qué es |
|---|---|
| `count` | Cantidad de productos en esta respuesta |
| `id` | Id de la variante en Odoo (`product.product`). Es el identificador estable del producto |
| `code` | Referencia interna. `null` si el producto no tiene |
| `name` | Nombre del producto, con los valores de atributo de la variante entre paréntesis (`Camisa (XL)`), sin la referencia. En el idioma del usuario de la API |
| `price` | Precio de venta del producto más el precio extra de la variante. Sin impuestos, sin listas de precios, en la moneda de la compañía |
| `quantity` | Cantidad libre: lo que hay en las ubicaciones internas de las compañías del usuario de la API menos lo ya reservado para entregas. Los servicios y los productos sin control de inventario dan `0.0` |

Una lista vacía también es `200`: `{"count": 0, "products": []}`.

## Errores

Los errores en JSON tienen siempre esta forma:

```json
{"error": {"code": "INVALID_PARAMETER", "field": "modified_since", "message": "Fecha no válida: 18/10/2026. Use AAAA-MM-DD o AAAA-MM-DDTHH:MM:SS, en UTC."}}
```

- `code`: código fijo en mayúsculas. Es el que la tienda debe usar para decidir qué hacer.
- `field`: el parámetro con el problema, o `null` si el error no es de un parámetro.
- `message`: explicación en español para una persona. Puede cambiar de redacción.

| HTTP | `code` | Cuándo | Qué hacer |
|---|---|---|---|
| 400 | `INVALID_PARAMETER` | Un parámetro con formato inválido, una categoría que no existe, un parámetro desconocido o repetido | Corregir la consulta: `field` dice cuál |
| 403 | `FORBIDDEN` | El usuario no es interno (por ejemplo, un usuario del portal) o le falta un permiso | Usar el usuario de la tienda |
| 405 | (sin JSON) | Un método distinto de GET | Usar GET |
| 303 | (sin JSON) | Sin sesión válida, en un servidor con una sola base o con filtro de bases: Odoo redirige a `/web/login` | Volver a abrir la sesión |
| 404 | (sin JSON) | Sin sesión válida, en un servidor con varias bases sin filtro: Odoo no sabe en qué base buscar la ruta | Volver a abrir la sesión |
| 500 | `INTERNAL_ERROR` | Un error inesperado del servidor. La respuesta no trae detalles; la traza queda en el registro de Odoo | Reintentar más tarde y avisar si se repite |

Un dato mal escrito por la tienda nunca da 500. El 405, el 303 y el 404 los responde Odoo antes de llegar a este módulo, por eso no traen el JSON de error.

## Ejemplos

Salidas reales contra la base de prueba local (`sia_navegador`, datos en [Cómo probarlo](#cómo-probarlo)):

```bash
# Muebles (id 7) y su subcategoría Sillas, con stock, modificados desde el 1 de septiembre
curl -s -b cookies.txt "http://localhost:8069/api/v1/products?category_id=7&in_stock=true&modified_since=2026-09-01T00:00:00Z"
# 200 {"count": 2, "products": [{"id": 11, "code": "TIENDA-001", "name": "Escritorio", "price": 150.0, "quantity": 8.0},
#                              {"id": 12, "code": "TIENDA-002", "name": "Silla", "price": 40.0, "quantity": 3.0}]}

curl -s -b cookies.txt "http://localhost:8069/api/v1/products?modified_since=18/10/2026"
# 400 {"error": {"code": "INVALID_PARAMETER", "field": "modified_since", "message": "Fecha no válida: 18/10/2026. Use AAAA-MM-DD o AAAA-MM-DDTHH:MM:SS, en UTC."}}

curl -s -b cookies.txt "http://localhost:8069/api/v1/products?category_id=999"
# 400 {"error": {"code": "INVALID_PARAMETER", "field": "category_id", "message": "No existe una categoría con id 999."}}

curl -s -b cookies.txt "http://localhost:8069/api/v1/products?categ=7"
# 400 {"error": {"code": "INVALID_PARAMETER", "field": "categ", "message": "Parámetro desconocido: categ. Los admitidos son category_id, in_stock y modified_since."}}
```

## Seguridad

- Los productos se buscan con los permisos del usuario de la API, así que las reglas de Odoo (por ejemplo, la de multicompañía) siguen aplicando.
- La cantidad libre se calcula con `sudo()`, solo sobre los productos ya encontrados. Odoo calcula esa cantidad leyendo los movimientos de inventario (`stock.move`), y leerlos pide el grupo Inventario / Usuario. Con `sudo()` el usuario de la tienda no necesita ese grupo: si sus credenciales se filtran, no sirven para mover inventario. Lo fija la prueba `test_api_user_has_no_inventory_rights`.
- Las compañías del cálculo siguen siendo las del usuario de la API.

## Cómo probarlo

```bash
./odoo test -i prueba-tecnica -d <base_nueva> -m shop_integration_api
```

El comando termina con código 0 aunque haya pruebas con error: hay que leer la línea `... of N tests` del final.

Las pruebas (`tests/test_products_api.py`) llaman a la API por HTTP con un usuario interno sin grupos de Ventas ni de Inventario:

| Criterio | Prueba |
|---|---|
| Solo productos activos y vendibles | `test_without_filters_only_active_and_saleable` |
| Formato de la respuesta, orden, código `null`, cantidad libre | `test_response_format` |
| Cada filtro solo | `test_filter_category_includes_subcategories`, `test_filter_in_stock`, `test_filter_in_stock_false_is_no_filter`, `test_filter_modified_since`, `test_filter_modified_since_variant_attributes` |
| Filtros combinados | `test_filters_combined` (seis combinaciones, una con resultado vacío) |
| Fecha mal escrita: 400 claro, nunca 500 | `test_invalid_date` (once valores: mes 13, 30 de febrero, `01/10/2026`, con espacio, con huso horario, dígitos de ancho completo, vacío...) |
| Otros valores inválidos | `test_invalid_category`, `test_invalid_in_stock`, `test_unknown_and_repeated_parameters` |
| Acceso | `test_requires_session`, `test_portal_user_forbidden`, `test_access_error_is_forbidden`, `test_only_get`, `test_api_user_has_no_inventory_rights` |
| Error inesperado sin detalles | `test_unexpected_error_is_json_without_details` |

A mano, en la base local `sia_navegador` (solo local, no se entrega). Usuarios: `tienda`/`tienda` (usuario de la API), `portal`/`portal` y `admin`/`admin`. Productos:

| id | Referencia | Producto | Categoría | Libre | Notas |
|---|---|---|---|---|---|
| 11 | TIENDA-001 | Escritorio | Muebles | 8 | |
| 12 | TIENDA-002 | Silla | Muebles / Sillas | 3 | Subcategoría |
| 13 | TIENDA-003 | Lámpara | Muebles | 0 | Sin stock |
| 14 | TIENDA-004 | Mesa | Muebles | 0 | 2 a mano, las 2 reservadas |
| 15 | | Instalación | Muebles | 0 | Servicio, sin referencia |
| 16 | TIENDA-005 | Estante | Otros | 4 | |
| 17 | TIENDA-006 | Insumo interno | Muebles | 5 | No se puede vender: no sale |
| 18 | TIENDA-007 | Producto archivado | Muebles | 5 | Archivado: no sale |

Todos con fecha de modificación 2026-10-01 00:00:00 UTC.

## Cómo se verificó

- Pruebas en una base nueva: `0 failed, 0 error(s) of 18 tests`.
- Antes de escribir el controlador, las 15 pruebas de entonces fallaban con 404 (la ruta no existía).
- Se rompieron a propósito tres cosas a la vez: la categoría sin subcategorías, `modified_since` sin la plantilla y la cantidad a mano en lugar de la libre. Fallaron las pruebas que cubren cada una (`9 failed of 16`). Después se restauró el código.
- Las dos pruebas agregadas después de la revisión de código fallaban con el controlador anterior (`2 failed of 18`).
- Los ejemplos de este README se corrieron con `curl` contra Odoo en marcha.
- Instalación en una base nueva: el registro no tiene `WARNING`, `ERROR` ni mensajes de docutils de este módulo. Quedan dos mensajes de docutils (`<string>:38: (ERROR/3)` y `<string>:43: (WARNING/2)`) que salen al cargar el módulo `mail` de Odoo.
- Linter del repositorio (`.pylintrc` y `.pylintrc-mandatory`): solo marca que el autor del manifest no es la OCA, igual que en los otros módulos del repositorio.

## Qué se reusa de Odoo

- La sesión y `auth='user'` para la autenticación.
- `product.product` con sus campos: `sale_ok`, `active`, `default_code`, `lst_price` (precio con el extra de la variante), `display_name` (nombre con atributos) y `categ_id` con `child_of` para las subcategorías.
- `free_qty` de Inventario para la cantidad libre, también como filtro.
- Las reglas de registro de producto para multicompañía.

## Supuestos

- La cantidad disponible es la libre (a mano menos reservado), no la cantidad a mano: lo reservado ya está prometido a otro pedido.
- Los servicios se incluyen porque se pueden vender. Siempre salen con cantidad `0.0`.
- El precio es el de la ficha del producto, sin impuestos ni listas de precios, en la moneda de la compañía.
- `modified_since` cuenta cambios en la variante, en la plantilla y en los valores de atributo de la variante: ahí viven el código, el nombre y el precio.
- Un parámetro desconocido es un error y no se ignora: así un error de tipeo (`categ=7`) no devuelve el catálogo completo sin avisar.
- Una categoría que no existe es un error y no una lista vacía.

## Preguntas al cliente

1. ¿La cantidad que publica la tienda debe ser la libre (a mano menos reservado) o la que hay a mano?
2. ¿La tienda vende servicios o solo productos físicos? Hoy los servicios salen con cantidad 0.
3. ¿Los precios se publican con impuestos? ¿En qué moneda, y con alguna lista de precios?
4. ¿Cómo debe enterarse la tienda de que un producto dejó de venderse? (ver la primera limitación)

## Limitaciones conocidas

- Un producto archivado o que deja de venderse desaparece de la respuesta. Con `modified_since`, la tienda no recibe ninguna señal de esa baja. Mientras tanto, la tienda puede hacer cada cierto tiempo una consulta sin `modified_since` y retirar los productos que ya no vienen.
- Un movimiento de inventario no cambia la fecha de modificación del producto, así que `modified_since` no trae los productos cuya cantidad cambió. Para actualizar cantidades hay que consultar sin `modified_since`, o con `in_stock`.
- Si el servidor tiene varias bases sin filtro, sin sesión responde 404 y no 303 (ver [Errores](#errores)).
- El catálogo sale completo en una sola respuesta, sin paginación.
- Los parámetros se aceptan solo como están escritos aquí: `in_stock=True` o `in_stock=1` responden 400. También responden 400 el parámetro que algunos clientes HTTP agregan para evitar la caché (`_=`) y `debug=1`.
