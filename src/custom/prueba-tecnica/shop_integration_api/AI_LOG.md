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
  - Usé créditos de Claude Code en la nube para parte del trabajo más pesado (escribir código y
    pruebas), para optimizar tiempo y créditos. Después lo probé y ajusté en el entorno local.

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

---

# Tramo C — paginación, Idempotency-Key, aviso de entrega y openapi.yaml

## Prompts clave (tramo C)

Resúmenes, no citas textuales:

1. Proponer el tramo C con cada decisión abierta explicada con contexto y ejemplos, y una recomendación para cada una.
   - La IA planteó cinco decisiones: paginar siempre o solo cuando se pide; si `Idempotency-Key` es opcional u obligatoria y qué responder cuando se repite; qué entregas avisan a la tienda; con qué calendario se reintenta el aviso, y dónde se configura y cómo se firma.
2. "Recomendadas": aprobé las cinco recomendaciones.
3. Misma metodología que en los tramos anteriores: primero las pruebas, el código en commits separados por parte (paginación, idempotencia, aviso) y la documentación al final.
4. Revisar el tramo sin subir nada hasta integrar el ejercicio 4, y después "continúa": correr las pruebas en Odoo, revisar el código y corregir lo que saliera.
   - La IA corrió el rojo de cada commit `[TEST]` y las pruebas completas, pasó `/code-review` y el linter del repositorio, y confirmó con mutaciones que las pruebas detectan los errores. Me dejó una decisión abierta: qué significa `fully_delivered` cuando lo que falta de un pedido se cancela.
5. "Dame un ejemplo para decidir": la IA lo explicó con un pedido de 10 sillas y 6 en el almacén, con y sin entrega pendiente. Pregunté también cómo se entera el cliente de lo que falta; quedó explicado en el README («Cómo seguir un pedido con los avisos») y como pregunta a la tienda.
6. "Comprueba con capturas si todo está como debería": la IA recorrió la prueba en el navegador y me mostró las capturas paso por paso. Confirmé.

## Qué decidí yo (tramo C)

- **Paginar siempre**, 100 por defecto y 500 como máximo, con `next` que conserva los filtros, aunque cambie el contrato del tramo A. Queda documentado como cambio de contrato.
- **`Idempotency-Key` opcional**: sin ella el POST sigue como en el tramo B. Al repetir, `201` con el mismo pedido y `Idempotent-Replayed: true`; con otro contenido, 409; un 422 no gasta la clave; claves por usuario y sin vencimiento.
- **Avisar en cada entrega validada** de los pedidos creados por la API, también las parciales.
- **Reintentar cualquier respuesta que no sea 2xx** a los 1, 5, 15 y 60 minutos y luego cada 6 horas hasta cerca de un día; después, «Fallido» con un botón «Reintentar». El envío siempre en segundo plano, nunca durante la validación.
- **URL y secreto en Ajustes, solo para administradores**, con firma HMAC-SHA256 y un id por aviso.
- **`fully_delivered` es `true` cuando ya no queda nada por entregar**, también si lo que falta se cancela (validar una entrega parcial sin entrega pendiente). Antes solo era `true` si llegaba todo lo pedido: cuando se cancelaba lo que faltaba, la tienda se quedaba esperando un aviso que nunca llegaba.

## Decisiones de la IA dentro de lo aprobado

- El bloque «Tienda en línea» va dentro de **Ajustes generales** y no como una sección propia: Odoo muestra cada sección de Ajustes con un icono propio, y este módulo no tiene.
- Sin URL **o sin secreto** no se encola ningún aviso, para que nunca salga uno sin firma.
- El calendario quedó en 1, 5, 15 y 60 minutos y cuatro intentos más cada 6 horas: unas 25 horas en total.
- «Reintentar» vuelve a empezar la serie completa de reintentos.
- Las redirecciones no se siguen (un 3xx es un fallo) y la espera por respuesta es de 10 segundos.
- La tarea programada procesa hasta 50 avisos por corrida y como mucho durante 60 segundos, confirma cada aviso enviado para no reenviarlo si se corta, bloquea cada fila antes de enviarla (`FOR UPDATE SKIP LOCKED`) y se vuelve a programar para el próximo aviso pendiente sin esperar su intervalo de 5 minutos.
- La entrega del aviso es «al menos una vez»: la tienda debe ignorar un id de aviso repetido, el `event_id` del cuerpo, que va firmado. Queda en el README y en `openapi.yaml`.
- En la revisión: un cuerpo con un sustituto suelto (`\ud800`) responde 400 `INVALID_JSON` (no es texto Unicode válido); los enteros de la consulta se rechazan por largo antes de convertirlos; la colisión esperada de la clave de idempotencia no se registra como error de consulta (`mute_logger`); el aviso no descarga la respuesta de la tienda (`stream=True`); el `cr.commit()` de la tarea programada queda con su justificación para el linter.
- No se aplicaron cuatro hallazgos de `/code-review`, con su motivo:
  - Paginar solo cuando se pide, o con `/api/v2`: paginar siempre lo decidí yo, sabiendo que cambia el contrato.
  - Paginar por id y firmar una marca de tiempo: cambian el contrato con la tienda; quedan como limitación y pregunta.
  - El doble cálculo de stock con `in_stock=true`: en Odoo 18 ese filtro es una consulta agrupada sobre las existencias (`_search_field_by_quants`), no un cálculo por producto.
  - Los disparadores que la tarea programada deja para el próximo aviso: Odoo los borra solo a la semana (`_gc_cron_triggers`).

## Lo que la IA hizo mal (tramo C)

- La primera versión de la prueba que comprueba que la clave de idempotencia no guarda el cuerpo hacía un reemplazo de texto enredado sobre el volcado del registro. Se simplificó antes del commit de pruebas.
- El primer ejemplo de respuesta paginada del README mostraba en la misma página los productos 11 y 15 con un total de 3, lo que no cuadra con los datos de prueba documentados (los productos 12 a 14 también se venden). Salió al releer la documentación y se cambió por un ejemplo que sí cuadra.
- Los ejemplos de `curl` del GET eran salidas reales del tramo A. Al cambiar el formato, la IA los iba a actualizar sin volver a correrlos; se dejó escrito en el README que el formato nuevo es el que fijan las pruebas y que no se volvieron a correr.
- Escribió dos pruebas que fallaban con el código correcto, porque las escribió sin correrlas. La del 409 `IDEMPOTENCY_KEY_IN_USE` sembraba una clave con otro resumen del cuerpo, así que el código respondía `IDEMPOTENCY_KEY_REUSED`. La de la clave `"   "` no llegaba al servidor: `requests` no deja mandar una cabecera que empieza con espacio. Salieron en la primera corrida en Odoo (`1 failed, 1 error(s) of 86 tests`).
- Dejó una rama de código que ninguna petición podía alcanzar (una clave confirmada sin pedido), y la prueba del 409 apuntaba a esa rama y no a dos peticiones a la vez. Lo encontró `/code-review`; ahora la prueba usa una conexión aparte que reserva la clave mientras la petición espera.
- Dos datos mal escritos daban 500: un entero de miles de dígitos en `page`, `page_size` o `category_id` (este desde el tramo A) y un sustituto suelto en el cuerpo del POST (desde el tramo B). La colisión esperada de la clave dejaba un error de consulta en el registro de Odoo, y el aviso descargaba la respuesta entera de la tienda. Lo encontró `/code-review`; se agregaron pruebas que fallaban (`7 failed, 0 error(s) of 87 tests`) y se corrigió.
- El README y `openapi.yaml` pedían descartar avisos repetidos por la cabecera `X-Shop-Event-Id`, que no va firmada. Además, la recomendación del tramo A para las bajas («una consulta sin `modified_since`») ya no servía con la paginación: la tienda retiraría productos que siguen a la venta. Lo encontró `/code-review`.
- `fully_delivered` nunca llegaba a `true` si lo que faltaba se cancelaba. Lo encontró `/code-review`; lo decidí yo con un ejemplo.
- El README decía que las devoluciones no avisan, pero ninguna prueba lo fijaba: quitar el filtro de entregas de salida no rompía nada. Salió al elegir las mutaciones; se agregó la prueba.
- El tramo B había dejado tres avisos del linter del repositorio (dos mensajes traducibles con varios valores sin nombre y un `string` redundante) que ningún documento mencionaba. Salieron al correr el linter en el tramo C.
- En la primera corrida de mutaciones aplicó cinco a la vez, y una tapó a otra: la página vacía hacía fallar la prueba de consultas antes de comparar el número. Se corrió esa mutación sola.
- En el tramo B recomendó un usuario de la tienda con lo mínimo, pero no advirtió qué pasa al actualizar una base que tenía el tramo A sin Ventas. Odoo instala Ventas y Facturación y da a todos los usuarios internos los grupos de su plantilla de usuario por defecto, entre ellos los de administrador. Salió al preparar la base de la prueba en el navegador: el usuario de la tienda quedó como administrador de Ventas y de Facturación. Se comprobó en el código de Odoo 18 (`_apply_groups_to_existing_employees`) y quedó en «Seguridad» del README.

## Cómo lo verifiqué (tramo C)

- Rojo de cada commit `[TEST]` en una base nueva, por la razón esperada, y después las pruebas en una base nueva de Odoo 18: `0 failed, 0 error(s) of 89 tests` del módulo y `0 failed, 0 error(s) of 209 tests` de los cuatro módulos juntos. El detalle está en el README («Cómo se verificó (tramo C)»).
- Mutaciones (stock por producto, contenido de la clave, devoluciones, envío durante la validación, página inicial): cada una hizo fallar sus pruebas.
- Linter del repositorio: solo el aviso de autor OCA. `openapi.yaml`: OpenAPI 3.1 válido.
- Por la hora, le pedí a la IA que recorriera la prueba en el navegador, como excepción. La hizo con un navegador automatizado (Playwright) sobre una base local actualizada desde el tramo A, con los mismos pasos que me había preparado, y me mostró las capturas de cada paso con lo que debía verse. Las revisé y di el visto bueno. El detalle está en el README.
- Después confirmé en el navegador, en la misma base, que todo estaba así.
