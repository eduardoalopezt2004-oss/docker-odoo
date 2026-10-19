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

## Lo que escribí yo sin IA

> Borrador de la IA con las decisiones que tomé. Lo reescribo con mis palabras antes de subir.

- El formato de error del enunciado y las decisiones del contrato: cantidad libre, 400 para un parámetro desconocido y para una categoría inexistente, servicios incluidos y la limitación de `modified_since`.
- La decisión de `sudo()` acotado en lugar de darle el grupo de Inventario al usuario de la tienda.
- La verificación en el navegador con el usuario de la tienda y con un usuario del portal.
