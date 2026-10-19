# AI_LOG — shop_integration_api

## Herramientas
- Claude Code (Claude Opus 5.5) en VS Code, con un esquema de trabajo que definí para esta prueba:
  - Reglas propias de Odoo 18 que se cargan en cada tarea (sintaxis, seguridad, pruebas, commits),
    con perfiles distintos para corrección urgente, migración y desarrollo nuevo.
  - Recordatorios automáticos en cada instrucción: formato de commits, alcance del repositorio
    y que nada se sube sin mi aprobación.
  - Revisión obligatoria de cada tramo contra los criterios del enunciado antes de cerrarlo.
  - Condición de cierre: pruebas en base nueva, linter del repositorio y mi verificación en el
    navegador antes de cada push.

Delegué en la IA la redacción de código, pruebas y documentos, dentro de esas reglas. Mi trabajo
fue definir el método, revisar y aprobar cada propuesta, decidir los supuestos y verificar el
resultado, para dedicar el tiempo a revisar y decidir en lugar de a escribir.

## Prompts clave

1. "Antes del código, define el contrato del endpoint: parámetros, formato de cada uno, respuesta, errores y códigos HTTP. Lo valido yo. No adelantes nada de los tramos B y C. Empieza por Entender y detente."
   - Propuso el contrato después de revisar el código de Odoo 18. Encontró que, sin sesión, `auth='user'` redirige a `/web/login` en vez de responder 401, y que un movimiento de inventario no cambia la fecha de modificación del producto. Me dejó siete decisiones abiertas.
2. "Formato de error del PDF (úsalo desde A, con códigos en mayúsculas) [...] Decisiones: 2 free_qty, como supuesto y pregunta al cliente. 3 sí, 400. 4 sí, 400. 5 incluir servicios, como pregunta. 6 sí, como limitación."
   - Le pasé el formato de error del enunciado y aprobé el contrato con esas decisiones.
3. "Crea feat/shop_integration_api desde ahí y sigue hasta el cierre con el contrato aprobado."
   - Escribió primero las pruebas y comprobó que fallaban porque la ruta no existía. Después escribió el controlador y pasó `/code-review`.
4. Decisión a mitad del tramo: calcular la cantidad libre exige el grupo Inventario / Usuario. Elegí `sudo()` acotado al cálculo antes que darle ese grupo al usuario de la tienda, el mismo criterio que usé en T-200.

## Lo que la IA hizo mal

- En la fase Entender dijo que un usuario interno ya podía leer el stock. Solo había revisado el permiso sobre `stock.quant`, pero el cálculo de la cantidad también lee `stock.move`. Se vio en la primera corrida de las pruebas con el controlador (11 pruebas con 500 y `AccessError` en el registro). Me planteó las dos salidas y decidí yo.
- Propuso un formato de error propio sin saber que el enunciado ya fijaba uno. Lo dejó como pregunta abierta y le pasé el del PDF.
- El contrato decía que sin sesión la respuesta es 303. Al probar con `curl` contra Odoo en marcha salió 404: el servidor local tiene varias bases y Odoo no sabe en cuál buscar la ruta. La IA lo encontró, verificó los dos casos y lo documentó en el README.
- `/code-review` encontró que `modified_since` no veía un cambio de precio extra ni de nombre de un valor de atributo de una variante, y que un `AccessError` respondía 500 en vez de 403. Se agregaron pruebas que fallaban, se corrigió y pasaron.
- La primera prueba de mutación (romper el código a propósito para ver si las pruebas lo detectan) no rompió nada: la IA usó una variable de shell en un comando de WSL lanzado desde Windows, y llegó vacía. Las pruebas dieron `0 failed` y casi lo tomó como bueno. Lo vio porque el diff salió vacío. La repitió con un script y fallaron las pruebas esperadas.
- En la base de prueba manual, la IA reservó la Mesa directamente en el stock, sin una entrega. El planificador de Inventario borra las reservas que no tienen un movimiento detrás, y la borró segundos después de que la IA lo comprobara. Por eso `in_stock=true` traía 4 productos y no 3. Salió en la verificación; se corrigió con una entrega real que reserva las dos unidades.

## Lo que escribí yo sin IA

Partes donde preferí no delegar:

- Las decisiones del contrato: usar desde el tramo A el formato de error del enunciado, publicar la cantidad libre, responder 400 a un parámetro desconocido o a una categoría inexistente, incluir los servicios y dejar los cambios de stock como limitación de `modified_since`.
- El `sudo()` acotado al cálculo de la cantidad. La otra opción era darle el grupo de Inventario al usuario de la tienda, y con sus credenciales se podría mover inventario.
- La verificación. Probé la API en el navegador con el usuario de la tienda y con uno del portal, y pedí una verificación automatizada del resto de los casos. Ahí salió que los datos de prueba no tenían la reserva de la Mesa; se corrigieron.

---

# Tramo B — POST /api/v1/orders, clave de API y log de llamadas

## Prompts clave (tramo B)

Resúmenes, no citas textuales:

1. Definir el contrato del tramo B (autenticación del POST, formato del cuerpo, errores y qué se guarda en el log) y verificar contra el código de Odoo 18 lo que condicione el diseño.
   - La IA propuso el contrato y señaló los puntos del código de Odoo que lo condicionan: la verificación de claves en `res.users.apikeys`, que `auth='bearer'` rechaza la clave mala sin JSON y sin pasar por el log, que con `auth='none'` Odoo abre un cursor de solo lectura (hace falta `readonly=False`), que las reglas de registro se aplican al crear (el vendedor por defecto es el del cliente) y que `vat` se guarda tal como se escribió.
2. Mis decisiones sobre el contrato: el pedido queda como cotización; el GET acepta la clave o la sesión; el usuario de la tienda es el vendedor con «solo documentos propios»; en las líneas la clave se llama `default_code` (como en el ejemplo de error del enunciado) y no `code`; y los supuestos 1 a 4 (referencia externa sin unicidad, productos sin referencia no se piden, líneas repetidas no se suman, log sin depuración ni límite de llamadas).
3. Primero las pruebas, que deben fallar; después el código en commits separados; al final README y AI_LOG.

## Qué decidí yo (tramo B)

- **Cotización y no pedido confirmado.** La IA planteaba las dos salidas; elegí la cotización porque un vendedor debe revisar precio, lista de precios y pago, y porque no pasa por la confirmación de `sale_commission`. Acepto el costo: el stock no se reserva hasta confirmar y la última unidad podría venderse dos veces. Queda como pregunta al cliente.
- **Clave en lugar de sesión para el POST**, y que el POST no acepte la cookie: con cookie, otra página web podría crear pedidos con la sesión abierta de quien navega.
- **Que el GET acepte la clave o la sesión** y que todas sus llamadas queden en el log.
- **El usuario de la tienda como vendedor del pedido** en lugar de darle un permiso más amplio sobre pedidos de otros vendedores.
- **`sudo()` solo donde hace falta** y con comentario: crear la fila del log y ver si el dueño de la clave sigue activo.

## Lo que la IA hizo mal (tramo B)

- Iba a escribir en la documentación que un usuario normal solo puede crear claves de API de 1 día. Es incorrecto: el grupo «Usuario interno» permite claves de hasta 90 días; el límite de 1 día es para quien no tiene ese grupo (por ejemplo, un usuario del portal). Se corrigió en el README y en las pruebas: la clave del usuario del portal se crea con menos de un día y la de los internos con 30 días.
- En la primera versión de las pruebas, la clave del usuario del portal se creaba con 30 días de duración, pero esa duración no está permitida para quien no es usuario interno. Se corrigió antes de subir (ajuste agregado al commit de pruebas).
- La primera versión de una prueba para comprobar que el cliente y los productos se buscan una sola vez (no una por línea) quedó con código enredado y sin sentido. Se reemplazó por una prueba que cuenta las llamadas a `_find_customer` y `_find_products`.
- Para registrar el código de error en el log, la primera versión del controlador lo leía de la respuesta ya armada (`response.json`), lo que depende de un detalle de la clase de respuesta que no se pudo comprobar. Se cambió para guardar el código desde el lugar donde se produce el error.

- Al pedirle que comprobara todo lo hecho, la IA releyó el código contra las pruebas y encontró cinco errores en las pruebas que había escrito, que habrían fallado con el código correcto: la prueba de cuerpo vacío mandaba un GET y no un POST (`url_open` cambia de método cuando no hay cuerpo); la llamada «sin credenciales» del log del GET iba después de iniciar sesión, con la cookie todavía activa; una prueba suponía que existe la categoría con id 1; otra usaba un atributo de campo poco fiable para listar los campos del log; y otra fallaba si la base trae pedidos sin vendedor, que la regla de Odoo también deja ver. Se corrigieron en un commit aparte.

## Cómo lo verifiqué

- Corrí las pruebas en una base nueva de Odoo 18: 57 pruebas del módulo, sin fallos ni errores. Eso confirmó el uso de `res.users.apikeys`, `request.update_env`, `Model.has_access` y el parámetro `readonly` de las rutas.
- Quedaron pendientes por tiempo los ejemplos de `curl` contra Odoo en marcha y la prueba en el navegador con una clave real.
