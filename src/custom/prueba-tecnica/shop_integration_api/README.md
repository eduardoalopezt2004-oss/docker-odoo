# API de productos y pedidos para la tienda en línea (`shop_integration_api`)

Ejercicio 1 de la prueba técnica. La tienda en línea del cliente consulta en Odoo el catálogo que puede vender (código, nombre, precio y cantidad disponible de cada producto) y le manda sus pedidos. Este documento está escrito para quien programa la integración del lado de la tienda. El mismo contrato, en formato máquina, está en [`openapi.yaml`](openapi.yaml) (OpenAPI 3.1).

## Tramos

- [x] A: `GET /api/v1/products` con sesión de usuario, filtros y errores claros.
- [x] B: `POST /api/v1/orders` (crea una cotización), autenticación con clave (Bearer) y registro de llamadas. El `GET` acepta la clave o la sesión.
- [x] C: paginación con total, página y siguiente; `Idempotency-Key` en el POST; consultas del GET que no crecen con los productos; aviso firmado a la tienda al validar la entrega, con reintentos; `openapi.yaml`. Probado en Odoo en bases nuevas (ver [Cómo se verificó (tramo C)](#cómo-se-verificó-tramo-c)).

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

Si el servidor tiene varias bases y no tiene `db_filter`, una llamada sin cookie de sesión recibe un 404 de Odoo (sin JSON) antes de llegar a este módulo, porque no sabe en qué base buscar la ruta. Pasa en el entorno local. En producción se resuelve con `db_filter` (o `dbfilter` en `odoo.conf`) para que el servidor tenga una sola base visible; para probar en local, también sirve arrancar con `--db-filter='^<base>$'`. Con `curl`, otra salida es pedir antes `/web/login?db=<base>` guardando la cookie y mandarla junto con la clave: la cookie solo le dice a Odoo la base, y quien llama sigue siendo el dueño de la clave.

```bash
curl -s -c cookies.txt -o /dev/null "http://localhost:8069/web/login?db=<base>"
curl -s -b cookies.txt -H "Authorization: Bearer <clave>" "http://localhost:8069/api/v1/products?page_size=2"
```

## `GET /api/v1/products`

Devuelve los productos activos que se pueden vender (casilla **Sales** de la ficha del producto, campo `sale_ok`). Cada variante es un producto. La lista va ordenada por `id`.

### Parámetros

Todos son opcionales. Si se mandan varios, el producto tiene que cumplirlos todos.

| Parámetro | Formato | Qué hace |
|---|---|---|
| `category_id` | Entero positivo: el id de la categoría | Productos de esa categoría y de sus subcategorías |
| `in_stock` | `true` o `false` | `true`: solo productos con cantidad disponible mayor que cero. `false`: lo mismo que no mandarlo |
| `modified_since` | `AAAA-MM-DD` o `AAAA-MM-DDTHH:MM:SS`, en UTC, con `Z` final opcional (`2026-10-19T14:30:00Z`) | Productos cuyo código, nombre o precio pudo cambiar en esa fecha y hora o después. Una fecha sola cuenta desde las 00:00:00 UTC |
| `page` | Entero desde 1. Por defecto, 1 | Página que se pide (ver [Paginación](#paginación)) |
| `page_size` | Entero de 1 a 500. Por defecto, 100 | Productos por página |

No se aceptan otros parámetros, ni el mismo parámetro dos veces: responden 400.

### Respuesta

`200`, con `Content-Type: application/json`. Por ejemplo, `?page_size=2` con los datos de [Cómo probarlo](#cómo-probarlo):

```json
{
  "total": 6,
  "page": 1,
  "page_size": 2,
  "count": 2,
  "next": "/api/v1/products?page=2&page_size=2",
  "products": [
    {"id": 11, "code": "TIENDA-001", "name": "Escritorio", "price": 150.0, "quantity": 8.0},
    {"id": 12, "code": "TIENDA-002", "name": "Silla", "price": 40.0, "quantity": 3.0}
  ]
}
```

| Campo | Qué es |
|---|---|
| `total` | Productos que cumplen los filtros, sumando todas las páginas |
| `page`, `page_size` | La página y el tamaño de página de esta respuesta |
| `count` | Cantidad de productos en esta respuesta |
| `next` | Ruta de la página siguiente, con los mismos filtros. `null` en la última página |
| `id` | Id de la variante en Odoo (`product.product`). Es el identificador estable del producto |
| `code` | Referencia interna. `null` si el producto no tiene |
| `name` | Nombre del producto, con los valores de atributo de la variante entre paréntesis (`Camisa (XL)`), sin la referencia. En el idioma del usuario de la API |
| `price` | Precio de venta del producto más el precio extra de la variante. Sin impuestos, sin listas de precios, en la moneda de la compañía |
| `quantity` | Cantidad libre: lo que hay en las ubicaciones internas de las compañías del usuario de la API menos lo ya reservado para entregas. Los servicios y los productos sin control de inventario dan `0.0` |

Una lista vacía también es `200`: `{"total": 0, "page": 1, "page_size": 100, "count": 0, "next": null, "products": []}`.

### Paginación

Desde el tramo C el GET **siempre pagina**: sin `page` ni `page_size` devuelve la primera página de 100 productos. Es un cambio de contrato respecto a los tramos A y B, donde la respuesta traía el catálogo completo: una tienda que leía `products` de una sola llamada ahora tiene que seguir `next`.

Para recorrer el catálogo:

1. Pedir la primera página con los filtros que hagan falta: `/api/v1/products?in_stock=true&page_size=200`.
2. Mientras `next` no sea `null`, pedir la ruta de `next` (lleva los mismos filtros y el mismo `page_size`).

Una página después de la última responde `200` con la lista vacía y `next: null`. Un `page` o `page_size` que no sea un entero en su rango responde 400 `INVALID_PARAMETER` con el parámetro en `field`. La lista va ordenada por `id`, así que las páginas no se mezclan entre llamadas, pero si el conjunto cambia mientras la tienda recorre las páginas (se crea o se archiva un producto, o con `in_stock=true` uno se queda sin stock o vuelve a tenerlo), un producto puede saltarse o repetirse (ver [Tramo C: supuestos, limitaciones y preguntas](#tramo-c-supuestos-limitaciones-y-preguntas)).

La cantidad de consultas a la base no crece con los productos de la página: la cantidad libre se calcula para toda la página de una vez. Lo fija la prueba `test_query_count_does_not_grow_with_products`, que compara 3 y 30 productos.

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

### Reintentos sin duplicar: `Idempotency-Key`

Si la conexión se corta después de mandar el pedido y antes de recibir la respuesta, la tienda no sabe si el pedido se creó. Para reintentar sin crear otro, la tienda manda en el POST la cabecera `Idempotency-Key` con una clave suya, distinta para cada pedido (por ejemplo, un UUID), y repite exactamente la misma llamada con la misma clave:

```bash
curl -s -X POST https://<servidor>/api/v1/orders \
  -H "Authorization: Bearer <clave>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 3f0c8e2a-4b7d-4c1e-9a55-1d2e3f4a5b6c" \
  -d '{"customer_rif": "J-12345678-9", "external_ref": "WEB-1001", "lines": [{"default_code": "TIENDA-001", "quantity": 2}]}'
```

| Caso | Respuesta |
|---|---|
| Sin `Idempotency-Key` | Como en el tramo B: cada llamada crea un pedido |
| Clave nueva | `201` con el pedido nuevo |
| Misma clave y mismo contenido | `201` con el **mismo** pedido y la cabecera `Idempotent-Replayed: true`. No se crea otro |
| Misma clave y otro contenido | `409 IDEMPOTENCY_KEY_REUSED`. Para otro pedido, otra clave |
| Misma clave mientras la primera llamada todavía no termina | `409 IDEMPOTENCY_KEY_IN_USE`. Reintentar en unos segundos |
| Llamada que termina en error (por ejemplo, 422 por un código mal escrito) | La clave no se gasta: se corrige el cuerpo y se reintenta con la misma clave |

- La clave es opcional, de 1 a 255 caracteres ASCII visibles (el espacio cuenta; tabuladores y letras con tilde no). Una clave vacía o inválida responde `400 INVALID_IDEMPOTENCY_KEY`.
- «Mismo contenido» se compara como JSON: no importan el orden de los campos ni los espacios.
- Las claves son de cada usuario de la API (dos usuarios pueden usar la misma clave sin chocar) y no vencen.
- La respuesta repetida trae el pedido como está ahora: si un vendedor ya lo confirmó, `state` es `sale` y los montos son los actuales.
- Odoo guarda la clave, el usuario, el pedido y un resumen SHA-256 del cuerpo, no el cuerpo. Solo los administradores pueden leer esas filas.

### Errores del POST

Misma forma que en el GET. `field` es la ruta exacta del dato (`customer_rif`, `lines[1].quantity`, `lines[1].default_code`); el índice de las líneas empieza en 0. Hay un solo error por respuesta. Antes que nada se revisan las credenciales (401/403) y el método (405). Después se revisa la forma de todo el cuerpo: primero los campos desconocidos, luego `customer_rif`, `external_ref` y `lines`, y las líneas en orden (una cantidad cero o negativa se detecta aquí). Al final se busca el cliente y luego los productos, línea por línea; en esta etapa se detecta la cantidad que queda en 0 al redondear a la unidad del producto.

| HTTP | `code` | `field` | Cuándo |
|---|---|---|---|
| 400 | `INVALID_JSON` | `null` | El cuerpo no es JSON o no es un objeto |
| 400 | `INVALID_IDEMPOTENCY_KEY` | `Idempotency-Key` | La cabecera viene vacía, con más de 255 caracteres o con caracteres que no son ASCII visibles |
| 401 | `UNAUTHORIZED` | `null` | Sin cabecera `Authorization`, con otro esquema (Basic), o con una clave inválida, vencida, borrada o de un usuario archivado. Lleva `WWW-Authenticate: Bearer` |
| 403 | `FORBIDDEN` | `null` | Clave válida de un usuario del portal, o de un usuario sin permiso para crear pedidos |
| 405 | `METHOD_NOT_ALLOWED` | `null` | Método distinto de POST (con cabecera `Allow: POST`) |
| 409 | `IDEMPOTENCY_KEY_REUSED` | `Idempotency-Key` | La clave ya se usó con otro contenido |
| 409 | `IDEMPOTENCY_KEY_IN_USE` | `Idempotency-Key` | Otra llamada con la misma clave todavía no termina |
| 422 | `REQUIRED_FIELD` | el campo | El campo falta, es `null` o viene vacío, o `lines` no trae líneas |
| 422 | `INVALID_FIELD` | el campo | Tipo o formato inválido: RIF mal escrito, cantidad `"2"` o `true`, campo desconocido |
| 422 | `CUSTOMER_NOT_FOUND` | `customer_rif` | No hay ningún cliente con ese RIF |
| 422 | `PRODUCT_NOT_FOUND` | `lines[i].default_code` | No hay ningún producto vendible con ese código |
| 422 | `INVALID_QUANTITY` | `lines[i].quantity` | Cero, negativa, o que queda en 0 al redondear a la precisión de la unidad de venta |
| 422 | `AMBIGUOUS_REFERENCE` | `customer_rif` o `lines[i].default_code` | Más de un cliente con ese RIF o más de un producto con ese código |
| 500 | `INTERNAL_ERROR` | `null` | Error inesperado. Si la llamada alcanzó a escribir algo, se deshace: no queda un pedido a medias |

Los errores 4xx son de la tienda y se corrigen; un 422 repetido con el mismo cuerpo siempre da el mismo resultado. Un 500 o un corte de red se pueden reintentar: con `Idempotency-Key` el reintento no duplica el pedido. Sin ella, cada reintento puede crear otro pedido.

La cabecera `Idempotency-Key` se revisa antes que el cuerpo, y la clave se busca después de revisar la forma del cuerpo: un cuerpo mal formado da su 400 o 422 aunque la clave ya exista.

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

## Aviso a la tienda al validar la entrega

Cuando en Odoo se valida una entrega de un pedido creado por `POST /api/v1/orders`, Odoo le avisa a la tienda con un `POST` a la URL que ella indique. Una entrega parcial avisa con lo que salió en ella; cuando se valida el resto, llega otro aviso.

### Cómo se envía

- **En segundo plano.** Al validar, Odoo solo deja el aviso en una cola; lo envía una tarea programada (`Tienda en línea: enviar avisos de entrega`) en cuanto puede. Si la tienda está caída o tarda, quien valida la entrega no espera ni ve ningún error.
- **Reintentos.** Cualquier respuesta que no sea 2xx, o ninguna respuesta en 10 segundos, cuenta como fallo. Se reintenta a los 1, 5, 15 y 60 minutos y luego cada 6 horas, cuatro veces más: unas 25 horas en total. Después el aviso queda **Fallido**. Las redirecciones no se siguen: un 3xx también es un fallo.
- **Al menos una vez.** Si Odoo se cae justo después de enviar y antes de anotar el envío, el aviso puede llegar dos veces. La tienda debe ignorar un aviso cuyo `event_id` ya procesó. Ese id va en el cuerpo, que está firmado. La cabecera `X-Shop-Event-Id` trae el mismo valor pero no va firmada: para descartar repetidos se usa el del cuerpo, después de verificar la firma.
- **Sin orden garantizado.** Un aviso que falló sale en su reintento, y para entonces puede haber llegado otro más nuevo del mismo pedido. Para saber cuál es el último, la tienda compara `delivery.date_done`.

### Qué recibe la tienda

Cabeceras:

| Cabecera | Qué es |
|---|---|
| `Content-Type` | `application/json` |
| `X-Shop-Event-Id` | Id único del aviso (UUID), igual al `event_id` del cuerpo y el mismo en cada reintento. No va firmado: para descartar repetidos, usar el del cuerpo |
| `X-Shop-Signature` | `sha256=` y el HMAC-SHA256 en hexadecimal del cuerpo, con el secreto configurado en Odoo |

Cuerpo:

```json
{
  "event": "order.delivered",
  "event_id": "0b6c1f4e-3d2a-4f5b-8c7d-9e0f1a2b3c4d",
  "order": {"id": 42, "name": "S00042", "external_ref": "WEB-1001"},
  "delivery": {
    "name": "WH/OUT/00007",
    "date_done": "2026-10-20T14:03:00Z",
    "lines": [{"product_id": 11, "default_code": "TIENDA-001", "quantity": 2.0}]
  },
  "fully_delivered": false
}
```

| Campo | Qué es |
|---|---|
| `order.id`, `order.name` | El `id` y el `name` que devolvió el POST |
| `order.external_ref` | La `external_ref` que mandó la tienda |
| `delivery.name` | Número de la entrega en Odoo |
| `delivery.date_done` | Fecha y hora de la validación, en UTC |
| `delivery.lines` | Lo que salió en **esta** entrega: id y referencia del producto (los mismos del GET) y cantidad, en la unidad del pedido |
| `fully_delivered` | `true` si con esta entrega ya no queda nada por entregar del pedido: lo que faltaba se entregó o se canceló. No quiere decir que llegó todo lo pedido: para saber cuánto llegó, sumar `delivery.lines` de los avisos del pedido. Los servicios no cuentan |

El aviso no lleva precios ni datos del cliente: la tienda ya los tiene.

### Cómo seguir un pedido con los avisos

La tienda sabe lo que pidió; con los avisos sabe lo que salió y si falta algo. Por ejemplo, un pedido de 10 sillas cuando en el almacén hay 6:

| Qué pasa en Odoo | Avisos que llegan | Qué deduce la tienda |
|---|---|---|
| Se validan 6 y se crea una entrega pendiente con las otras 4 | 6 sillas con `fully_delivered: false`; cuando se valida la pendiente, 4 sillas con `fully_delivered: true` | Con el primero: llegaron 6 y las 4 restantes vienen en otra entrega. Con el segundo: pedido completo |
| Se validan 6 sin crear entrega pendiente (Odoo cancela las otras 4) | 6 sillas con `fully_delivered: true` | No viene nada más: pidió 10 y llegaron 6, así que se cancelaron 4 |

El aviso no dice cuándo saldrá lo pendiente. Si alguien cancela en Odoo una entrega pendiente sin validar nada, no sale ningún aviso (ver [Tramo C: supuestos, limitaciones y preguntas](#tramo-c-supuestos-limitaciones-y-preguntas)).

Odoo no le escribe por su cuenta al cliente de la tienda: eso lo hace la tienda con estos avisos. Si se prefiere que Odoo mande un correo al cliente en cada entrega validada, se activa en **Inventario → Configuración → Ajustes**, opción «Confirmación de correo electrónico». En ese caso conviene que la tienda no mande el suyo, para que el cliente no reciba dos.

### Cómo verifica la firma la tienda

La tienda calcula el HMAC-SHA256 del cuerpo **tal como llegó** (los bytes, antes de interpretar el JSON) con el mismo secreto, y lo compara en tiempo constante. Ejemplo en Python:

```python
import hashlib
import hmac

def aviso_valido(cuerpo: bytes, firma: str, secreto: str) -> bool:
    esperada = "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, firma or "")
```

Si la firma no coincide, la tienda responde un 4xx y no procesa el aviso. Responder 2xx confirma el aviso; Odoo no lee el cuerpo de la respuesta.

### Configuración (en Odoo)

1. Como administrador, abrir **Ajustes → Ajustes generales** y buscar el bloque **Tienda en línea**.
2. Escribir la **URL** que dio la tienda y el **Secreto** acordado con ella (una cadena larga y aleatoria; se comparte por un canal seguro, no por correo). Guardar.

Sin URL o sin secreto no se encola ningún aviso: así nunca sale un aviso sin firma. La firma se calcula al enviar, así que si se cambia el secreto, los avisos que estaban pendientes salen firmados con el nuevo.

### Seguimiento

Los administradores ven los avisos en **Ajustes → Técnico → Avisos a la tienda** (con el modo desarrollador): pedido, entrega, estado (Pendiente, Enviado, Fallido), intentos, próximo intento, último código HTTP y último error. Un aviso **Fallido** tiene el botón **Reintentar**, que lo vuelve a poner en la cola con la serie de reintentos completa.

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
| 400 | `INVALID_PARAMETER` | Un parámetro con formato inválido, una categoría que no existe, un parámetro desconocido o repetido, o un `page` o `page_size` fuera de rango | Corregir la consulta: `field` dice cuál |
| 401 | `UNAUTHORIZED` | Ni clave ni sesión válidas (ver [Conectarse](#conectarse)). Lleva la cabecera `WWW-Authenticate: Bearer` | Mandar la clave, o abrir la sesión de nuevo |
| 403 | `FORBIDDEN` | El usuario no es interno (por ejemplo, un usuario del portal) o le falta un permiso | Usar el usuario de la tienda |
| 405 | `METHOD_NOT_ALLOWED` | Un método distinto de GET | Usar GET |
| 404 | (sin JSON) | Servidor con varias bases sin `db_filter` y sin cookie de sesión: Odoo no sabe en qué base buscar la ruta | Ver [Varias bases de datos](#varias-bases-de-datos) |
| 500 | `INTERNAL_ERROR` | Un error inesperado del servidor. La respuesta no trae detalles; la traza queda en el registro de Odoo | Reintentar más tarde y avisar si se repite |

Un dato mal escrito por la tienda nunca da 500. El 404 de las varias bases lo responde Odoo antes de llegar a este módulo, por eso no trae el JSON de error. El mensaje del 401 no dice si la clave existe.

El GET registra todas sus llamadas en el log (ver [Registro de llamadas](#registro-de-llamadas)). Filtros, respuesta y errores del GET son los mismos del tramo A, salvo el 303 que ahora es 401, el 405 que ahora trae JSON y la paginación del tramo C.

## Ejemplos

Estas llamadas se corrieron con `curl` contra la base de prueba local (`sia_navegador`, datos en [Cómo probarlo](#cómo-probarlo)) en el tramo A. Aquí se muestran con el formato del tramo C: los campos de paginación y el mensaje del parámetro desconocido, que ahora nombra `page` y `page_size`, son los que fijan las pruebas, pero no se volvieron a correr con `curl`.

```bash
# Muebles (id 7) y su subcategoría Sillas, con stock, modificados desde el 1 de septiembre
curl -s -b cookies.txt "http://localhost:8069/api/v1/products?category_id=7&in_stock=true&modified_since=2026-09-01T00:00:00Z"
# 200 {"total": 2, "page": 1, "page_size": 100, "count": 2, "next": null,
#      "products": [{"id": 11, "code": "TIENDA-001", "name": "Escritorio", "price": 150.0, "quantity": 8.0},
#                   {"id": 12, "code": "TIENDA-002", "name": "Silla", "price": 40.0, "quantity": 3.0}]}

curl -s -b cookies.txt "http://localhost:8069/api/v1/products?modified_since=18/10/2026"
# 400 {"error": {"code": "INVALID_PARAMETER", "field": "modified_since", "message": "Fecha no válida: 18/10/2026. Use AAAA-MM-DD o AAAA-MM-DDTHH:MM:SS, en UTC."}}

curl -s -b cookies.txt "http://localhost:8069/api/v1/products?category_id=999"
# 400 {"error": {"code": "INVALID_PARAMETER", "field": "category_id", "message": "No existe una categoría con id 999."}}

curl -s -b cookies.txt "http://localhost:8069/api/v1/products?categ=7"
# 400 {"error": {"code": "INVALID_PARAMETER", "field": "categ", "message": "Parámetro desconocido: categ. Los admitidos son category_id, in_stock, modified_since, page y page_size."}}
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
- Tramo C, `Idempotency-Key`: las claves se leen y se crean con `sudo()`, solo las del usuario que llama, porque el usuario de la tienda no tiene permisos sobre ese modelo (igual que con el log). La respuesta repetida lee el pedido con `sudo()` porque quien revisa la cotización puede haberle cambiado el vendedor, y la respuesta debe ser la misma. Una restricción única en la base (`unique(user_id, key)`) impide dos pedidos con la misma clave aunque lleguen dos llamadas a la vez.
- Tramo C, aviso: se encola con `sudo()` porque quien valida puede ser un almacenista sin permisos sobre pedidos de venta ni sobre los avisos; solo se leen las entregas validadas y sus pedidos. La URL y el secreto están en los parámetros del sistema, que solo leen los administradores; el secreto se muestra oculto en Ajustes. El aviso va firmado (HMAC-SHA256) y sin datos del cliente, y no se envía sin firma.
- **Al actualizar una base que tenía el tramo A**, revisar los grupos del usuario de la tienda. Desde el tramo B el módulo depende de Ventas, así que Odoo instala Ventas y Facturación si no estaban. Al instalarlos, Odoo da a todos los usuarios internos que ya existen los grupos de su plantilla de usuario por defecto, entre ellos **Ventas / Administrador** y **Facturación / Administrador**, también al usuario de la tienda. Después de actualizar hay que dejarle solo «Usuario interno» y **Ventas / Usuario: solo documentos propios**. Si no, su clave sirve para administrar Ventas y Facturación.

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
| Otros valores inválidos | `test_invalid_category` (incluye un id de 5000 dígitos), `test_invalid_in_stock`, `test_unknown_and_repeated_parameters` |
| Acceso | `test_requires_credentials`, `test_portal_user_forbidden`, `test_access_error_is_forbidden`, `test_only_get`, `test_api_user_has_no_inventory_rights` |
| Error inesperado sin detalles | `test_unexpected_error_is_json_without_details` |

Las pruebas del tramo B están en `tests/test_orders_api.py` (POST, claves, permisos, log) y en `tests/test_products_api.py` (GET con clave o sesión).

Las del tramo C:

| Criterio | Prueba |
|---|---|
| Paginación con total, página y siguiente; `next` conserva los filtros | `test_products_pagination.py`: `test_pages_with_metadata_and_next`, `test_next_keeps_every_filter`, `test_defaults_and_maximum`, `test_page_beyond_the_last_is_empty`, `test_invalid_page_and_page_size` |
| Las consultas del GET no crecen con los productos | `test_query_count_does_not_grow_with_products` (3 y 30 productos, mismas consultas) |
| `Idempotency-Key`: misma clave y contenido, mismo pedido; otro contenido, 409 | `test_orders_idempotency.py`: `test_same_key_same_content_returns_the_same_order`, `test_same_content_written_differently_is_the_same`, `test_same_key_other_content_is_409` |
| Sin clave o con claves distintas, pedidos distintos; claves por usuario; un 422 no gasta la clave; clave inválida | `test_without_key_each_post_creates_an_order`, `test_different_keys_create_different_orders`, `test_keys_are_per_api_user`, `test_failed_request_does_not_use_the_key`, `test_invalid_key` |
| Dos peticiones a la vez con la misma clave: la segunda recibe 409 `IDEMPOTENCY_KEY_IN_USE` y no crea pedido | `test_key_in_use_by_a_request_not_finished_is_409` (una conexión aparte reserva la clave mientras la petición espera) |
| Cuerpo con un sustituto suelto: 400, no 500 | `test_orders_api.py`: `test_lone_surrogate_is_invalid_json_not_500` |
| Las claves no guardan el cuerpo y solo las leen administradores; unicidad en la base | `test_keys_store_no_body_and_only_admins_read_them`, `test_unique_key_per_user_in_the_database` |
| Validar la entrega encola el aviso sin llamar a la tienda | `test_delivery_webhook.py`: `test_validating_the_delivery_queues_a_notice_without_calling_the_store` |
| Tienda caída: quien valida no se bloquea ni ve el error | `test_store_down_does_not_block_whoever_validates` |
| Contenido, firma y reintentos | `test_payload`, `test_successful_send_is_signed_and_marked_sent`, `test_any_non_2xx_is_retried_on_schedule_until_failed`, `test_manual_retry_of_a_failed_notice` |
| Cuándo se avisa | `test_each_partial_delivery_notifies`, `test_only_orders_created_by_the_api_notify`, `test_returns_do_not_notify`, `test_without_url_nothing_is_queued`, `test_post_marks_the_order` |
| `fully_delivered` con lo que falta cancelado | `test_partial_delivery_without_backorder_has_nothing_left_to_deliver` |
| Ajustes y permisos | `test_settings_store_url_and_secret`, `test_only_admins_see_the_notices` |

Las pruebas del aviso no llaman a ninguna tienda real: reemplazan `requests.post` por una respuesta simulada.

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
- Tramo C: `search_count` y `offset`/`limit` del ORM para paginar; `stock.picking._action_done` y `qty_delivered` de `sale_stock` para la entrega; las tareas programadas de Odoo (`ir.cron` y su disparador para no esperar al intervalo); `res.config.settings` con `config_parameter` para la URL y el secreto; `requests`, que ya trae Odoo, para el envío.

## Supuestos

- Solo los usuarios internos usan la API. Un usuario del portal (un cliente con acceso a «Mi cuenta») recibe 403 `FORBIDDEN` aunque tenga sesión. La API muestra cantidades de inventario, que no son información para clientes. Además, los módulos `product` y `stock` no le dan al portal permiso de lectura sobre productos ni stock: sin este bloqueo, su consulta terminaría en un error 500. Lo fija la prueba `test_portal_user_forbidden`.
- La cantidad disponible es la libre (a mano menos reservado), no la cantidad a mano: lo reservado ya está prometido a otro pedido.
- Los servicios se incluyen porque se pueden vender. Siempre salen con cantidad `0.0`.
- El precio es el de la ficha del producto, sin impuestos ni listas de precios, en la moneda de la compañía.
- `modified_since` cuenta cambios en la variante, en la plantilla y en los valores de atributo de la variante: ahí viven el código, el nombre y el precio.
- Un parámetro desconocido es un error y no se ignora: así un error de tipeo (`categ=7`) no devuelve el catálogo completo sin avisar.
- Una categoría que no existe es un error y no una lista vacía.

## Preguntas al cliente

Sobre lo que necesita la tienda:

1. ¿La tienda vende servicios o solo productos físicos? Hoy los servicios salen con cantidad 0.
2. ¿Los precios se publican con impuestos? ¿En qué moneda, y con alguna lista de precios?

Que salen de cómo funciona Odoo:

3. ¿La cantidad que publica la tienda debe ser la libre (a mano menos reservado) o la que hay a mano? Odoo separa lo que ya está reservado para otras entregas.
4. ¿Cómo debe enterarse la tienda de que un producto dejó de venderse? Un producto archivado o que deja de venderse desaparece de la respuesta, también con `modified_since`, así que la tienda no recibe una señal de la baja (ver la primera limitación).

## Limitaciones conocidas

- Un producto archivado o que deja de venderse desaparece de la respuesta. Con `modified_since`, la tienda no recibe ninguna señal de esa baja. Mientras tanto, la tienda puede recorrer cada cierto tiempo el catálogo completo sin `modified_since`, siguiendo `next` hasta el final, y retirar los productos que no vinieron en ninguna página. Desde el tramo C una sola llamada trae solo la primera página: retirar lo que no vino en ella borraría productos que siguen a la venta.
- Un movimiento de inventario no cambia la fecha de modificación del producto, así que `modified_since` no trae los productos cuya cantidad cambió. Para actualizar cantidades hay que consultar sin `modified_since`, o con `in_stock`.
- Si el servidor tiene varias bases sin filtro, sin sesión responde 404 y no 303 (ver [Errores](#errores)).
- ~~El catálogo sale completo en una sola respuesta, sin paginación.~~ Resuelto en el tramo C (ver [Paginación](#paginación)).
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

- **La referencia externa no es única:** si la tienda reintenta un pedido (por ejemplo, tras un corte de red antes de recibir la respuesta), se crea otro pedido con la misma `external_ref`. Resuelto en el tramo C cuando la tienda manda `Idempotency-Key` (ver [Reintentos sin duplicar](#reintentos-sin-duplicar-idempotency-key)); sin la cabecera sigue igual.
- **El log no se depura solo.** Crece con cada llamada hasta que alguien lo limpie.
- **No hay límite de llamadas por minuto.**
- La clave dura hasta 90 días y hay que renovarla a mano antes de que venza; no hay aviso.
- El cliente se busca con una consulta SQL que filtra por RIF normalizado y otra con el ORM que aplica las reglas de acceso del usuario de la tienda; los productos, con una sola búsqueda para todas las líneas.

### Preguntas al cliente

Sobre lo que necesita la tienda:

1. ¿Cuánto tiempo se guarda el log de llamadas, y quién lo depura?
2. ¿Quién revisa las cotizaciones de la tienda y confirma el pago?

Que salen de cómo funciona Odoo:

3. El stock no se reserva hasta que un vendedor confirma la cotización, así que la última unidad podría venderse dos veces. ¿Es aceptable, o la tienda debe descontarla de su propio inventario, o las cotizaciones deben reservar stock?
4. Los productos sin referencia interna no se pueden pedir (el POST pide el código). ¿Hay productos vendibles sin referencia que la tienda necesite pedir?

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

## Tramo C: supuestos, limitaciones y preguntas

### Supuestos

- **El GET siempre pagina, 100 por defecto y 500 como máximo.** Una respuesta sin límite crece con el catálogo y puede tardar o fallar con muchos productos. Es un cambio de contrato respecto a los tramos A y B (ver [Paginación](#paginación)).
- **`Idempotency-Key` es opcional.** Sin ella el POST se comporta como en el tramo B, así una tienda ya integrada no se rompe. Recomendamos mandarla siempre.
- **Las claves son de cada usuario de la API y no vencen.** Si la tienda repite una clave meses después con el mismo contenido, recibe el pedido viejo; con otro contenido, un 409.
- **Solo avisan los pedidos creados por la API.** El POST los marca (campo `shop_api_order`). Los pedidos creados en Odoo, o por la API antes de instalar el tramo C, no avisan.
- **Avisa cada entrega validada, también las parciales**, con lo que salió en ella. Con entregas en varios pasos (recoger, empaquetar, enviar) avisa solo el paso de salida al cliente (tipo de operación «Entrega»). Las devoluciones y las cancelaciones no avisan.
- **`fully_delivered` es `true` cuando ya no queda nada por entregar**: el pedido no tiene entregas al cliente sin validar ni cancelar. También es `true` cuando lo que falta se cancela, por ejemplo al validar una entrega parcial sin crear entrega pendiente: así la tienda sabe que no llegará otro aviso. Cuánto llegó lo dicen las líneas de los avisos (ver [Cómo seguir un pedido con los avisos](#cómo-seguir-un-pedido-con-los-avisos)).
- **La configuración va en Ajustes generales**, en un bloque «Tienda en línea», y solo la ven los administradores.

### Limitaciones conocidas

- La paginación es por posición (`page`): si el conjunto cambia mientras la tienda recorre las páginas (se crea o se archiva un producto, o con `in_stock=true` uno se queda sin stock), un producto puede saltarse o salir dos veces. La tienda puede recorrer de nuevo el catálogo de vez en cuando, como ya se recomienda para las bajas. Paginar por id («los productos con id mayor que el último recibido») lo evitaría (pregunta 7).
- El aviso no dice cuándo saldrá lo que queda pendiente, y cancelar en Odoo una entrega pendiente sin validar nada no avisa (preguntas 4 y 5).
- Los avisos de un mismo pedido pueden llegar desordenados si uno falla y se reintenta; la tienda compara `delivery.date_done`.
- La firma cubre el cuerpo, no una marca de tiempo: quien capture un aviso puede reenviarlo tal cual. La tienda lo descarta por su `event_id` repetido.
- Los avisos y las claves de idempotencia no se depuran solos, igual que el log.
- Si la URL o el secreto no estaban configurados cuando se validó una entrega, ese aviso no se crea después.
- El envío depende de las tareas programadas de Odoo: con un servidor sin hilos para ellas (`max_cron_threads = 0`), los avisos se quedan pendientes.
- Un aviso **Fallido** solo vuelve a salir si un administrador pulsa **Reintentar**; no hay alerta por correo.

### Preguntas a la tienda

Sobre lo que necesita la tienda:

1. ¿A qué URL debe llegar el aviso de entrega, y pueden verificar la firma HMAC-SHA256 con un secreto compartido? ¿Cómo prefieren recibir ese secreto?
2. ¿Qué tamaño de página les sirve? Hoy son 100 productos por defecto y 500 como máximo.
3. ¿Mandarán `Idempotency-Key` en cada pedido? Sin ella, un reintento tras un corte de red puede duplicar el pedido.
4. ¿Necesitan avisos de otros cambios del pedido (confirmación, cancelación, devolución)? Hoy solo se avisa cuando se valida una entrega.

Que salen de cómo funciona Odoo:

5. ¿Necesitan mostrarle al cliente cuándo llegará lo que quedó pendiente? Odoo podría mandar esa fecha, pero solo sirve si alguien en el almacén la mantiene al día: hoy la entrega pendiente hereda la fecha de la entrega original.
6. ¿Quién le avisa al cliente de cada entrega: la tienda, con estos avisos, o el correo que Odoo puede mandar al validarla? Si avisan los dos, el cliente recibe dos mensajes.
7. ¿Les sirve paginar por número de página, o prefieren paginar por id? Con páginas, un producto que se queda sin stock mientras la tienda recorre el catálogo con `in_stock=true` puede hacer que se salte otro.

## Cómo se verificó (tramo C)

- Las pruebas se escribieron antes que el código, en commits `[TEST]` separados, para cada parte: paginación, `Idempotency-Key` y aviso. Cada commit de pruebas, corrido en una base nueva con el código anterior, falló por la razón esperada:
  - Paginación: `14 failed, 1 error(s) of 63 tests` (`page_size` era un parámetro desconocido y la respuesta no traía `page`).
  - `Idempotency-Key`: `9 failed, 4 error(s) of 74 tests` (el reintento creaba otro pedido, faltaba `Idempotent-Replayed` y no existía el modelo de claves).
  - Aviso: el archivo de pruebas no cargaba porque el modelo del aviso no existía.
- La primera corrida con todo el código dio `1 failed, 1 error(s) of 86 tests`: dos pruebas mal escritas (ver el AI_LOG). Se corrigieron, y la revisión de código encontró casos que daban 500 o dejaban errores en el registro; sus pruebas nuevas fallaron antes de la corrección (`7 failed, 0 error(s) of 87 tests`). También fallaron antes de su corrección las pruebas de `fully_delivered` con lo que falta cancelado (`1 failed, 0 error(s) of 89 tests`).
- Mutaciones: se rompieron a propósito el cálculo de stock (producto por producto), la comparación del contenido de `Idempotency-Key`, el filtro de devoluciones, el envío en segundo plano y la página inicial. Cada una hizo fallar las pruebas que la cubren; la del stock, por ejemplo, subió las consultas de 43 a 232 con 30 productos. Después se restauró el código.
- Pruebas en una base nueva de Odoo 18 (`./odoo test -i prueba-tecnica -d <base_nueva> -m shop_integration_api`): `0 failed, 0 error(s) of 89 tests`. Los cuatro módulos juntos: `0 failed, 0 error(s) of 209 tests`.
- Linter del repositorio (`.pylintrc` y `.pylintrc-mandatory`): solo marca que el autor del manifest no es la OCA, igual que en los otros módulos.
- `openapi.yaml` es OpenAPI 3.1 válido (`openapi-spec-validator`).
- Prueba a mano, en una base local actualizada desde el tramo A (`sia_navegador`), con los pasos de abajo. La recorrió la IA con un navegador automatizado (Playwright), por pedido de Eduardo; él revisó las capturas de cada paso y dio el visto bueno:
  - Ajustes: el bloque «Tienda en línea» guarda la URL y el secreto.
  - GET: con `page_size=2` trae `"total": 6` y `next`; la página 3 trae `"next": null`.
  - `Idempotency-Key`: dos POST iguales devuelven el mismo pedido (`S00001`), el segundo con `Idempotent-Replayed: true`. Con otra cantidad, 409 `IDEMPOTENCY_KEY_REUSED`. En Ventas hay una sola cotización.
  - Entrega parcial sin entrega pendiente: 8 de 10 Escritorios, validados sin crear entrega pendiente. El aviso sale en el primer intento, con `fully_delivered: true`, y el receptor confirma la firma.
  - Entrega parcial con entrega pendiente y la tienda caída: 4 de 6 Estantes. La validación no espera. El aviso queda pendiente con el error y el próximo intento a un minuto. Con el receptor encendido sale en el segundo intento, con `fully_delivered: false`.
  - «Reintentar»: un aviso fallido vuelve a la cola y se envía.
- Después, Eduardo confirmó en el navegador, en la misma base, que todo estaba así.

### Pasos de prueba a mano

1. Actualizar el módulo (`-u shop_integration_api`); el tramo C agrega la dependencia `sale_stock`.
2. GET: `curl -s -H "Authorization: Bearer <clave>" "http://localhost:8069/api/v1/products?page_size=2"` debe traer `total`, `page`, `page_size`, `count` y `next`; seguir `next` hasta que sea `null`. Con varias bases en el servidor, agregar la cookie de la base (ver [Varias bases de datos](#varias-bases-de-datos)).
3. `Idempotency-Key`: mandar dos veces el POST de [Reintentos sin duplicar](#reintentos-sin-duplicar-idempotency-key) con la misma clave. Las dos respuestas deben traer el mismo `id`, la segunda con `Idempotent-Replayed: true`, y en **Ventas → Cotizaciones** debe haber un solo pedido. Esa lista abre con el filtro «Mis cotizaciones», y el vendedor de los pedidos de la API es el usuario de la tienda: para verlos hay que quitar el filtro. Cambiar la cantidad y repetir con la misma clave: 409.
4. Aviso: levantar un receptor que responda 200 y sea alcanzable desde donde corre Odoo (si Odoo está en Docker, desde el contenedor). Por ejemplo, este, que además verifica la firma:

   ```python
   import hashlib, hmac
   from http.server import BaseHTTPRequestHandler, HTTPServer

   SECRETO = "secreto-de-prueba"

   class Receptor(BaseHTTPRequestHandler):
       def do_POST(self):
           cuerpo = self.rfile.read(int(self.headers["Content-Length"]))
           esperada = "sha256=" + hmac.new(SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()
           valida = hmac.compare_digest(esperada, self.headers.get("X-Shop-Signature", ""))
           print(self.headers["X-Shop-Event-Id"], "firma válida" if valida else "FIRMA INVÁLIDA", cuerpo.decode())
           self.send_response(200 if valida else 401)
           self.end_headers()

   HTTPServer(("0.0.0.0", 8000), Receptor).serve_forever()
   ```

5. En **Ajustes → Ajustes generales → Tienda en línea**, poner la URL del receptor y el secreto `secreto-de-prueba`.
6. Confirmar la cotización creada por la API y validar su entrega. La validación no debe esperar al receptor. Al poco tiempo (la tarea programada se dispara al validar, sin esperar su intervalo de 5 minutos), el receptor imprime el aviso con «firma válida» y en **Ajustes → Técnico → Avisos a la tienda** el aviso queda **Enviado**.
7. Detener el receptor y validar otra entrega: el aviso queda **Pendiente** con el error y el próximo intento a un minuto. Para ver el estado **Fallido** sin esperar 25 horas, se puede adelantar el próximo intento desde la base o desde el shell de Odoo; la prueba `test_any_non_2xx_is_retried_on_schedule_until_failed` recorre la serie completa.
