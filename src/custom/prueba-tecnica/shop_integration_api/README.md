# API de productos y pedidos para la tienda en línea (`shop_integration_api`)

Ejercicio 1 de la prueba técnica. La tienda en línea del cliente consulta en Odoo el catálogo que puede vender (código, nombre, precio y cantidad disponible de cada producto) y le manda sus pedidos. Este documento está escrito para quien programa la integración del lado de la tienda.

## Tramos

- [x] A: `GET /api/v1/products` con sesión de usuario, filtros y errores claros.
- [x] B: `POST /api/v1/orders` (crea una cotización), autenticación con clave (Bearer) y registro de llamadas. El `GET` acepta la clave o la sesión.
- [ ] C: no iniciado.

## Conectarse

Hay dos formas de autenticarse. El `POST /api/v1/orders` solo acepta la clave; el `GET /api/v1/products` acepta cualquiera de las dos.

Recomendamos un usuario solo para la tienda, con el tipo «Usuario interno» y el grupo **Ventas / Usuario: solo documentos propios** (`sales_team.group_sale_salesman`), sin grupos de Inventario. Ese usuario es el vendedor de los pedidos que crea la tienda y, con ese permiso, solo ve esos pedidos y no los de otros vendedores.

### Con clave (Bearer)

1. El usuario de la tienda entra a Odoo, abre **Preferencias → Seguridad de la cuenta → Nueva clave de API** y copia la clave (si la sección de claves no aparece, activar el modo desarrollador). Odoo la muestra una sola vez. Dura hasta 90 días (el grupo «Usuario interno» permite ese máximo); al vencer hay que crear otra.
2. La tienda manda la clave en cada llamada:

   ```bash
   curl -s -H "Authorization: Bearer <clave>" "https://<servidor>/api/v1/products?in_stock=true"
   ```

Si la llamada trae la cabecera `Authorization`, manda ella: una clave mala da 401 aunque también venga una cookie de sesión.

### Con sesión (solo el GET)

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

La sesión vence por inactividad. Si una consulta responde 401, hay que repetir el paso 1.

### Varias bases de datos

Si el servidor tiene varias bases y no tiene `db_filter`, una llamada sin cookie de sesión recibe un 404 de Odoo (sin JSON) antes de llegar a este módulo, porque no sabe en qué base buscar la ruta. Pasa en el entorno local. En producción se resuelve con `db_filter` (o `dbfilter` en `odoo.conf`) para que el servidor tenga una sola base visible; para probar en local, también sirve abrir una sesión en el navegador o arrancar con `--db-filter='^<base>$'`.

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

## `POST /api/v1/orders`

Crea un pedido para un cliente a partir del RIF y de los códigos de producto. Solo acepta la clave (ver [Conectarse](#conectarse)); la cookie de sesión no sirve.

El pedido queda como **cotización** (`state: "draft"`), no confirmado. Ver [Supuestos](#supuestos).

### Cuerpo

`Content-Type: application/json`. Ejemplo:

```json
{
  "customer_rif": "J-12345678-9",
  "external_ref": "WEB-1001",
  "lines": [
    {"default_code": "TIENDA-001", "quantity": 2},
    {"default_code": "TIENDA-002", "quantity": 1.5}
  ]
}
```

| Campo | Regla |
|---|---|
| `customer_rif` | Obligatorio. Una letra (V, E, J, P, G o C) y 9 dígitos. Admite guiones, puntos y espacios; da igual mayúscula o minúscula (`j-12345678-9`, `J123456789`). No se valida el dígito verificador. Se compara con el RIF de la ficha del cliente sin guiones, puntos ni espacios, y el pedido va a nombre de la empresa (si el RIF es de un contacto, la empresa a la que pertenece) |
| `external_ref` | Obligatorio, texto no vacío. Se guarda en el campo «Referencia del cliente» del pedido |
| `lines` | Obligatorio. Al menos una línea |
| `lines[i].default_code` | Obligatorio. La referencia interna exacta del producto (mayúsculas y minúsculas cuentan). Solo productos activos y que se pueden vender, como en el GET |
| `lines[i].quantity` | Obligatorio. Número mayor que 0, en la unidad de venta del producto. Admite decimales. Un texto (`"2"`) o `true` no sirven |

**`default_code` en el POST, `code` en el GET.** Es el mismo dato: la referencia interna del producto. El GET lo devuelve como `code`; las líneas del POST lo piden como `default_code` (el nombre del campo en Odoo). La tienda toma el `code` del GET y lo manda como `default_code`.

La tienda no manda precios: precios, impuestos y lista de precios los calcula Odoo según el cliente. Un campo que no esté en la tabla es un error (`INVALID_FIELD`), no se ignora. Dos líneas con el mismo código crean dos líneas en el pedido; no se suman.

### Respuesta

`201`, con `Content-Type: application/json`:

```json
{"id": 42, "name": "S00042", "state": "draft", "external_ref": "WEB-1001", "customer_id": 7, "amount_untaxed": 300.0, "amount_total": 348.0, "currency": "USD"}
```

| Campo | Qué es |
|---|---|
| `id` | Id del pedido en Odoo |
| `name` | Número de la cotización |
| `state` | `draft` (cotización) |
| `external_ref` | La referencia que mandó la tienda |
| `customer_id` | Id del cliente (la empresa) en Odoo |
| `amount_untaxed`, `amount_total` | Montos calculados por Odoo, sin y con impuestos |
| `currency` | Moneda del pedido |

### Errores del POST

Misma forma que en el GET. `field` es la ruta exacta del dato (`customer_rif`, `lines[1].quantity`, `lines[1].default_code`); el índice de las líneas empieza en 0. Hay un solo error por respuesta. Antes que nada se revisan las credenciales (401/403) y el método (405). Después se revisa la forma de todo el cuerpo: primero los campos desconocidos, luego `customer_rif`, `external_ref` y `lines`, y las líneas en orden (una cantidad cero o negativa se detecta aquí). Al final se busca el cliente y luego los productos, línea por línea; en esta etapa se detecta la cantidad que queda en 0 al redondear a la unidad del producto.

| HTTP | `code` | `field` | Cuándo |
|---|---|---|---|
| 400 | `INVALID_JSON` | `null` | El cuerpo no es JSON o no es un objeto |
| 401 | `UNAUTHORIZED` | `null` | Sin cabecera `Authorization`, con otro esquema (Basic), o con una clave inválida, vencida, borrada o de un usuario archivado. Lleva `WWW-Authenticate: Bearer` |
| 403 | `FORBIDDEN` | `null` | Clave válida de un usuario del portal, o de un usuario sin permiso para crear pedidos |
| 405 | `METHOD_NOT_ALLOWED` | `null` | Método distinto de POST (con cabecera `Allow: POST`) |
| 422 | `REQUIRED_FIELD` | el campo | El campo falta, es `null` o viene vacío, o `lines` no trae líneas |
| 422 | `INVALID_FIELD` | el campo | Tipo o formato inválido: RIF mal escrito, cantidad `"2"` o `true`, campo desconocido |
| 422 | `CUSTOMER_NOT_FOUND` | `customer_rif` | No hay ningún cliente con ese RIF |
| 422 | `PRODUCT_NOT_FOUND` | `lines[i].default_code` | No hay ningún producto vendible con ese código |
| 422 | `INVALID_QUANTITY` | `lines[i].quantity` | Cero, negativa, o que queda en 0 al redondear a la precisión de la unidad de venta |
| 422 | `AMBIGUOUS_REFERENCE` | `customer_rif` o `lines[i].default_code` | Más de un cliente con ese RIF o más de un producto con ese código |
| 500 | `INTERNAL_ERROR` | `null` | Error inesperado. Si la llamada alcanzó a escribir algo, se deshace: no queda un pedido a medias |

Los errores 4xx son de la tienda y se corrigen; un 422 repetido con el mismo cuerpo siempre da el mismo resultado. Un 500 se puede reintentar más tarde, pero ver la limitación sobre reintentos.

### Ejemplos

Con una clave de ejemplo (`0000…` no es una clave real) y una base con los datos de [Cómo probarlo](#cómo-probarlo):

```bash
curl -s -X POST http://localhost:8069/api/v1/orders \
  -H "Authorization: Bearer 0000000000000000000000000000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"customer_rif": "J-12345678-9", "external_ref": "WEB-1001", "lines": [{"default_code": "TIENDA-001", "quantity": 2}, {"default_code": "TIENDA-002", "quantity": 1.5}]}'
# 201 {"id": 42, "name": "S00042", "state": "draft", "external_ref": "WEB-1001", "customer_id": 7, "amount_untaxed": 300.0, "amount_total": 348.0, "currency": "USD"}

curl -s -X POST http://localhost:8069/api/v1/orders \
  -H "Authorization: Bearer 0000000000000000000000000000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"customer_rif": "J-12345678-9", "external_ref": "WEB-1002", "lines": [{"default_code": "TIENDA-001", "quantity": 1}, {"default_code": "ABC-123", "quantity": 1}]}'
# 422 {"error": {"code": "PRODUCT_NOT_FOUND", "field": "lines[1].default_code", "message": "No existe un producto con el código ABC-123"}}

curl -s -X POST http://localhost:8069/api/v1/orders \
  -H "Authorization: Bearer 0000000000000000000000000000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"customer_rif": "J-12345678-9", "external_ref": "WEB-1003", "lines": [{"default_code": "TIENDA-001", "quantity": "2"}]}'
# 422 {"error": {"code": "INVALID_FIELD", "field": "lines[0].quantity", "message": "lines[0].quantity debe ser un número, no un texto ni un booleano."}}

curl -s -X POST http://localhost:8069/api/v1/orders -H "Content-Type: application/json" -d '{}'
# 401 {"error": {"code": "UNAUTHORIZED", "field": null, "message": "Credenciales ausentes o inválidas. Mande la clave en la cabecera Authorization: Bearer."}}
```

Los números de pedido y montos de estos ejemplos son ilustrativos: dependen de la base. El formato de cada respuesta es el que fijan las pruebas (ver [Cómo se verificó](#cómo-se-verificó-tramo-b)).

## Registro de llamadas

Cada llamada a `GET /api/v1/products` y a `POST /api/v1/orders` deja una fila en el modelo `shop.api.log`, buena o mala, incluidas las que fallan por falta de credenciales.

| Campo | Qué guarda |
|---|---|
| Endpoint | Método y ruta, sin la consulta (`POST /api/v1/orders`) |
| Usuario | Dueño de la clave o de la sesión. Vacío si no se autenticó |
| Código HTTP | El código de la respuesta |
| Duración (ms) | Desde que la llamada entra al módulo hasta que se arma la respuesta |
| Código de error | El `code` del error. Vacío si salió bien |
| Fecha | Fecha y hora de la llamada |

No guarda cabeceras, cuerpo, consulta ni IP, así que la clave y los datos del cliente no llegan al log. Lo leen solo los administradores, en **Ajustes → Técnico → Llamadas a la API de la tienda** (el menú Técnico aparece con el modo desarrollador activado). Nadie lo edita desde la interfaz. Quien llama a la API no puede leerlo ni escribirlo; el módulo crea cada fila con `sudo()`, solo para eso.

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
| 401 | `UNAUTHORIZED` | Ni clave ni sesión válidas (ver [Conectarse](#conectarse)). Lleva la cabecera `WWW-Authenticate: Bearer` | Mandar la clave, o abrir la sesión de nuevo |
| 403 | `FORBIDDEN` | El usuario no es interno (por ejemplo, un usuario del portal) o le falta un permiso | Usar el usuario de la tienda |
| 405 | `METHOD_NOT_ALLOWED` | Un método distinto de GET | Usar GET |
| 404 | (sin JSON) | Servidor con varias bases sin `db_filter` y sin cookie de sesión: Odoo no sabe en qué base buscar la ruta | Ver [Varias bases de datos](#varias-bases-de-datos) |
| 500 | `INTERNAL_ERROR` | Un error inesperado del servidor. La respuesta no trae detalles; la traza queda en el registro de Odoo | Reintentar más tarde y avisar si se repite |

Un dato mal escrito por la tienda nunca da 500. El 404 de las varias bases lo responde Odoo antes de llegar a este módulo, por eso no trae el JSON de error. El mensaje del 401 no dice si la clave existe.

El GET registra todas sus llamadas en el log (ver [Registro de llamadas](#registro-de-llamadas)). Filtros, respuesta y errores del GET son los mismos del tramo A, salvo el 303 que ahora es 401 y el 405 que ahora trae JSON.

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
- La clave se verifica con `res.users.apikeys` de Odoo: se guarda cifrada, vence y se crea desde las preferencias del usuario. No se usa `auth='bearer'` de Odoo porque rechaza la clave mala con un 401 en texto plano, sin el JSON acordado y sin dejar la llamada en el log. Las rutas van con `auth='none'`, `csrf=False` y `readonly=False` y hacen la verificación ellas mismas.
- `csrf=False` es seguro porque la clave viaja en una cabecera que el navegador no agrega solo. Por eso el POST no acepta la cookie de sesión: con la cookie, otra página web podría crear pedidos con la sesión abierta de quien navega.
- El pedido se crea con los permisos del usuario de la tienda (no con `sudo()`). El vendedor del pedido es ese usuario, porque con «solo documentos propios» Odoo no deja crear un pedido cuyo vendedor sea otro, y el vendedor por defecto sería el del cliente. Quien revise la cotización puede cambiar el vendedor.
- `sudo()` también se usa para dos cosas más, ambas acotadas: ver si el dueño de la clave sigue activo, y crear la fila del log.
- La lógica de cada llamada corre dentro de un savepoint: si algo falla se deshace lo escrito y el log se escribe igual.

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
| Acceso | `test_requires_credentials`, `test_portal_user_forbidden`, `test_access_error_is_forbidden`, `test_only_get`, `test_api_user_has_no_inventory_rights` |
| Error inesperado sin detalles | `test_unexpected_error_is_json_without_details` |

Las pruebas del tramo B están en `tests/test_orders_api.py` (POST, claves, permisos, log) y en `tests/test_products_api.py` (GET con clave o sesión).

A mano, en la base local `sia_navegador` (solo local, no se entrega). Usuarios: `tienda`/`tienda` (usuario de la API), `portal`/`portal` y `admin`/`admin`. Productos:

| id | Referencia | Producto | Categoría | Libre | Notas |
|---|---|---|---|---|---|
| 11 | TIENDA-001 | Escritorio | Muebles | 8 | |
| 12 | TIENDA-002 | Silla | Muebles / Sillas | 3 | Subcategoría |
| 13 | TIENDA-003 | Lámpara | Muebles | 0 | Sin stock |
| 14 | TIENDA-004 | Mesa | Muebles | 0 | 2 a mano, las 2 reservadas por la entrega WH/OUT/00001 |
| 15 | | Instalación | Muebles | 0 | Servicio, sin referencia |
| 16 | TIENDA-005 | Estante | Otros | 4 | |
| 17 | TIENDA-006 | Insumo interno | Muebles | 5 | No se puede vender: no sale |
| 18 | TIENDA-007 | Producto archivado | Muebles | 5 | Archivado: no sale |

Todos con fecha de modificación 2026-10-01 00:00:00 UTC.

## Cómo se verificó (tramo A)

- Pruebas en una base nueva: `0 failed, 0 error(s) of 18 tests`.
- Antes de escribir el controlador, las 15 pruebas de entonces fallaban con 404 (la ruta no existía).
- Se rompieron a propósito tres cosas a la vez: la categoría sin subcategorías, `modified_since` sin la plantilla y la cantidad a mano en lugar de la libre. Fallaron las pruebas que cubren cada una (`9 failed of 16`). Después se restauró el código.
- Las dos pruebas agregadas después de la revisión de código fallaban con el controlador anterior (`2 failed of 18`).
- Los ejemplos de este README se corrieron con `curl` contra Odoo en marcha.
- En el navegador, con la base `sia_navegador`: la lista, cada filtro solo y combinados, los errores de fecha, de parámetro desconocido y de categoría, la consulta sin sesión y el 403 del usuario del portal.
- Instalación en una base nueva: el registro no tiene `WARNING`, `ERROR` ni mensajes de docutils de este módulo. Quedan dos mensajes de docutils (`<string>:38: (ERROR/3)` y `<string>:43: (WARNING/2)`) que salen al cargar el módulo `mail` de Odoo.
- Linter del repositorio (`.pylintrc` y `.pylintrc-mandatory`): solo marca que el autor del manifest no es la OCA, igual que en los otros módulos del repositorio.

## Qué se reusa de Odoo

- La sesión y `auth='user'` para la autenticación.
- `product.product` con sus campos: `sale_ok`, `active`, `default_code`, `lst_price` (precio con el extra de la variante), `display_name` (nombre con atributos) y `categ_id` con `child_of` para las subcategorías.
- `free_qty` de Inventario para la cantidad libre, también como filtro.
- Las reglas de registro de producto para multicompañía.

## Supuestos

- Solo los usuarios internos usan la API. Un usuario del portal (un cliente con acceso a «Mi cuenta») recibe 403 `FORBIDDEN` aunque tenga sesión. La API muestra cantidades de inventario, que no son información para clientes. Además, los módulos `product` y `stock` no le dan al portal permiso de lectura sobre productos ni stock: sin este bloqueo, su consulta terminaría en un error 500. Lo fija la prueba `test_portal_user_forbidden`.
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

## Tramo B: supuestos, limitaciones y preguntas

### Supuestos

- **El pedido queda como cotización (`draft`).** Un vendedor revisa el precio, la lista de precios y el pago antes de confirmar; la tienda no confirma sola. Además, la cotización no pasa por la confirmación de `sale_commission`, y si algo sale mal basta con cancelarla.
- **El stock no se reserva hasta confirmar.** Por eso la cantidad que devuelve el GET no baja con los pedidos de la tienda, y la última unidad podría venderse dos veces (ver la primera pregunta).
- **El usuario de la tienda es el vendedor del pedido** y tiene «solo documentos propios». Con eso Odoo le deja crear el pedido y la clave solo ve los pedidos de la tienda.
- **El RIF se compara normalizado** (sin guiones, puntos ni espacios, en mayúscula) contra el campo `vat` del cliente, que Odoo guarda tal como se escribió. No se valida el dígito verificador. Los contactos de una empresa copian el RIF de la empresa: cuentan como la misma empresa, no como un cliente repetido. Dos empresas con el mismo RIF dan `AMBIGUOUS_REFERENCE`.
- **Dos líneas con el mismo código crean dos líneas** en el pedido; no se suman.
- **El GET con clave devuelve lo mismo que con sesión.** Si viene la cabecera `Authorization`, se usa la clave y no se cae a la sesión.
- Para el cálculo de si la cantidad «queda en 0», se usa el redondeo de la unidad de medida del producto (por ejemplo, 0.4 cajas en una unidad que redondea a enteros).

### Limitaciones conocidas

- **La referencia externa no es única:** si la tienda reintenta un pedido (por ejemplo, tras un corte de red antes de recibir la respuesta), se crea otro pedido con la misma `external_ref`. El tramo C lo resuelve con `Idempotency-Key`.
- **El log no se depura solo.** Crece con cada llamada hasta que alguien lo limpie.
- **No hay límite de llamadas por minuto.**
- La clave dura hasta 90 días y hay que renovarla a mano antes de que venza; no hay aviso.
- El cliente se busca con una consulta SQL que filtra por RIF normalizado y otra con el ORM que aplica las reglas de acceso del usuario de la tienda; los productos, con una sola búsqueda para todas las líneas.

### Preguntas al cliente

1. El stock no se reserva hasta que un vendedor confirma la cotización, así que la última unidad podría venderse dos veces. ¿Es aceptable, o la tienda debe descontarla de su propio inventario, o las cotizaciones deben reservar stock?
2. Los productos sin referencia interna no se pueden pedir (el POST pide el código). ¿Hay productos vendibles sin referencia que la tienda necesite pedir?
3. ¿Cuánto tiempo se guarda el log de llamadas, y quién lo depura?
4. ¿Quién revisa las cotizaciones de la tienda y confirma el pago?

## Cómo se verificó (tramo B)

- Pruebas en una base nueva, Odoo 18.0, sin datos demo: 57 pruebas del módulo (tramos A y B), sin fallos ni errores. Las pruebas cubren la clave Bearer (válida, ausente, inválida, del portal), el POST con cada error y su `field`, la cotización creada, el log de llamadas buenas y fallidas sin la clave, y el GET con clave y con sesión.
- Instalación en esa base: el registro no tiene `WARNING` ni `ERROR` de este módulo.
- Pendiente por tiempo: los ejemplos de `curl` contra Odoo en marcha y la prueba en el navegador con una clave real (pasos abajo).

### Pasos de prueba en el navegador

1. Instalar o actualizar el módulo (`-u shop_integration_api`) en una base con los módulos `sale` y `stock`.
2. Crear el usuario de la tienda: usuario interno con **Ventas / Usuario: solo documentos propios**, y ponerle contraseña.
3. Entrar como ese usuario → **Preferencias → Seguridad de la cuenta → Nueva clave de API** y copiar la clave.
4. Crear un cliente con RIF `J-12345678-9` y productos con referencia interna `TIENDA-001` y `TIENDA-002`.
5. Si el servidor tiene varias bases, arrancar con `--db-filter='^<base>$'` (ver [Varias bases de datos](#varias-bases-de-datos)).
6. Correr los `curl` de [Ejemplos](#ejemplos) con la clave y abrir **Ventas → Cotizaciones**: la cotización debe aparecer con la referencia del cliente `WEB-1001` y el usuario de la tienda como vendedor.
7. Como administrador, abrir **Ajustes → Técnico → Llamadas a la API de la tienda** (con modo desarrollador) y ver una fila por llamada.
