# AI_LOG — payment_request

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

1. "Antes del código, lista lo que Carolina no dijo y propón supuestos para el tramo A; las preguntas a Carolina las escribo yo. No adelantes nada de los tramos B y C. Empieza por Entender y detente."
   - Mi prompt llegó sin el correo de Carolina: quedó el marcador donde tenía que pegarlo. La IA lo advirtió y marcó su lista de supuestos como provisional.
2. "Cruza los supuestos con el correo y avísame solo si alguno cambia. Después crea la rama y sigue hasta el cierre."
   - Cambió un supuesto: el correo dice que «cualquier empleado» puede pedir un pago, así que todo usuario interno es Solicitante.
   - Escribió primero las pruebas, que fallaban porque el módulo no definía los grupos. Después escribió el modelo y las vistas, y pasó `/code-review`. Para saber que las pruebas sirven, quitó a propósito el bloqueo de edición, los chequeos de grupo y el de auto-aprobación: fallaron las 4 pruebas que los cubren.
   - Mi prueba en el navegador llegó hasta la aprobación, no hasta el pago. La IA no dio el pago por probado en el navegador: lo comprobó con el usuario de Tesorería en un shell, deshaciendo el cambio al final, y el PR dice que ese paso falta.

## Lo que la IA hizo mal

- El diseño tenía un hueco de seguridad. En borrador se podía cambiar el solicitante en la misma escritura que envía la solicitud, así que un aprobador podía pasar su solicitud a otra persona y aprobarla él mismo. También se podía cambiar el número. Lo encontró `/code-review`: las reglas de registro se revisan antes de escribir, no después. Se agregó una prueba, falló, y se corrigió dejando fijos el número y el solicitante.
- El usuario administrador quedó en Aprobador y en Tesorería a la vez, contra mi decisión de que quien paga no aprueba. Lo encontró `/code-review` y se quitó.
- Al duplicar una solicitud se copiaba el solicitante, y la copia daba `AccessError`. Lo encontró `/code-review`. Ahora la copia queda a nombre de quien duplica, con su prueba.
- Había dos filas de permisos para Aprobador y Tesorería que no cambiaban nada, porque esos grupos ya heredan las de Solicitante. Lo encontró `/code-review` y se quitaron.

## Lo que escribí yo sin IA

Partes donde preferí no delegar:

- Las preguntas a Carolina y los supuestos para avanzar sin su respuesta.
- Las decisiones de control del tramo A: Tesorería separada de Aprobador, porque quien paga no aprueba; bloquear la auto-aprobación desde el tramo A, y que una solicitud rechazada no vuelva atrás.
- La verificación en el navegador con un usuario por grupo, hasta la aprobación.

---

# Tramo B — niveles de aprobación, rechazo con motivo, pago y reporte

## Prompts clave (tramo B)

1. "¿Podemos avanzar con el tramo B con lo que ya está en el repositorio y el enunciado?"
   - La IA revisó el estado del módulo y propuso un diseño apoyado en los supuestos del README del tramo A (un solo aprobador por nivel de monto, el aprobador no sale del jefe del empleado, pago suelto sin cruzar con factura). Dejó tres puntos abiertos para que yo decidiera.
2. "Sí a que el envío falle si el aprobador es quien pidió el pago; la pregunta del monto sin nivel, desarróllala."
   - Desarrolló el caso de un monto que ningún nivel cubre con tres opciones y sus riesgos.
3. "Sí, la opción 1." Con eso arrancó: primero las pruebas, después el código en commits separados y al final README y AI_LOG.

## Qué decidí yo (tramo B)

- **Sin nivel para el monto, el envío se bloquea** con un mensaje claro, en lugar de enviar sin aprobador o de tener un aprobador por defecto. Evita justo lo que el cliente quiere evitar: una solicitud enviada que nadie aprueba.
- **Si el aprobador del nivel es quien pidió el pago, el envío falla** y no se reasigna en silencio.

## Lo que la IA hizo mal (tramo B)

- Al ajustar las pruebas del tramo A (que ahora necesitan un nivel antes de enviar), en la prueba de «un aprobador no aprueba su propia solicitud» intentó llegar al estado enviado con `sudo().write`, que ya no es posible porque el envío falla. Lo vio al releer la prueba antes del commit y la cambió por una escritura SQL, para conservar la defensa en profundidad del tramo A.
- Al pedirle que comprobara todo lo hecho, releyó el código contra las pruebas y los permisos y encontró errores que había entregado como terminados:
  - El botón «Pago» y el PDF leían el `account.payment` con los permisos del usuario. Tesorería y el solicitante no tienen permisos de Contabilidad, así que imprimir una solicitud pagada habría dado error de acceso. Se agregaron el número y la fecha del pago como campos relacionados, y el botón quedó solo para quien tiene Contabilidad.
  - Tesorería no tenía garantizado leer los diarios contables, y sin eso no puede elegir el diario en el asistente. Se le dio solo lectura sobre `account.journal`.
  - El motivo del rechazo se publicaba como nota interna, que no avisa al solicitante. Ahora es un mensaje dirigido a él.
  - Cuatro pruebas habrían fallado con el código correcto: buscaba la palabra «aprobador» en un mensaje que no la tiene; leía el pago con el usuario solicitante; exigía un asiento publicado, cuando en Odoo 18 un pago puede publicarse sin asiento; y probaba un motivo vacío sin savepoint, lo que podía romper la transacción.
  - El README decía que el pago muestra un campo «Solicitud de pago» en su formulario, pero no hay vista que lo muestre. Se corrigió el texto.

- Las pruebas creaban usuarios sin correo. Al correrlas en una base nueva dieron 37 errores con la misma causa: Odoo no puede notificar la actividad del aprobador si quien envía no tiene correo. Lo vi en la primera corrida y se corrigió dándoles un correo de ejemplo.

## Cómo lo verifiqué

- Corrí las pruebas en una base nueva de Odoo 18 con `account` instalado: 49 pruebas del módulo, sin fallos ni errores después de la corrección. Eso confirmó el uso de `account.payment`, `_convert`, `activity_schedule` y el reporte.
- Pruebas en el navegador automatizadas por la IA, con un usuario por grupo: envío con aprobador asignado y su actividad, rechazo con motivo en el chatter, pago con diario y PDF con quién aprobó y cuándo. Después las revisé en el navegador para confirmar.

---

# Tramo C — pago en otra moneda, multi-compañía y concurrencia

## Prompts clave (tramo C)

Resúmenes, no citas textuales:

1. Seguir con el tramo C del ejercicio 4 con la misma metodología: la IA propone el plan, yo decido, después pruebas, código y documentación.
   - La IA propuso el plan sobre el código integrado y dejó tres decisiones abiertas: qué hacer si falta la tasa del día, cómo numerar con varias compañías y qué ve quien llega segundo cuando dos personas actúan a la vez.
2. Le pedí desarrollar mejor las opciones, con ejemplos, sin etiquetarlas con letras y nombrando siempre ejercicio y tramo. Con eso decidí (abajo).
3. "Haz el ejercicio 4, tramo C, como lo hablamos, y agrega los supuestos y preguntas que conversamos."
4. Antes de subir nada, pedí revisar todo el tramo contra el enunciado y contra el código de Odoo 18, sin tocar el repositorio mientras estaba ocupado, y mostrarme el plan con las decisiones que me tocaban.
   - La IA encontró los errores de abajo y me planteó las decisiones que me tocaban.

## Qué decidí yo (tramo C)

- **Tasa exacta del día del pago.** Si falta, el pago se bloquea con un aviso en lugar de usar una tasa anterior.
- **No automatizar la carga de tasas en este tramo.** Mi idea fue tomarlas automáticamente según la fuente que use el cliente, mostrando la fecha, con corrección manual y como función que se pueda apagar. Quedó escrita como propuesta en `ARCHITECTURE.md`, porque depende de qué tasa usen y de dónde la saquen, y es de toda la contabilidad, no de este módulo.
- **Numeración por compañía con código** (DA/SP/2026/0001), con filtro por compañía. Se me ocurrió para que cada compañía tenga su numeración seguida sin que el número se repita entre compañías. Sin código, cada compañía sigue con el contador general.
- **Aviso inmediato** para la segunda persona cuando dos actúan a la vez sobre la misma solicitud.
- **Preguntas nuevas para Carolina:** si llevan la contabilidad en Odoo, si manejan más de una empresa y si cada una necesita su numeración, y la pregunta de la tasa ampliada (qué tasa, de qué fuente, si ya la registran en Odoo, quién la carga y si les serviría tomarla automáticamente). También que el PDF muestre el monto pagado y la tasa.
- **Orden de trabajo:** primero lo que pide el enunciado y al final la numeración por compañía, que es un agregado nuestro y lo primero que se recortaría por tiempo.
- **La compañía queda fija desde que se crea la solicitud**, no solo desde que se envía, porque el número lleva el código de esa compañía.
- **La tasa exacta también cuando la solicitud y el diario usan la misma moneda extranjera**, porque el asiento en la moneda de la compañía se calcula con esa tasa.
- **Una prueba de concurrencia de punta a punta:** el aprobador en dos pestañas a la vez, con los métodos reales y dos conexiones a la base.
- **Reusar el código de una compañía queda como limitación escrita**, sin una regla nueva.

## Lo que la IA hizo mal (tramo C)

- Asumió que la tasa era la del BCV, sin que el correo ni el enunciado lo dijeran, y con ese supuesto argumentó contra automatizarla (que el BCV no tiene API oficial). Se lo corregí: la fuente es justamente una pregunta para Carolina. Quedó así en el README y en `ARCHITECTURE.md`.
- Planteó las decisiones abiertas con letras («2a», «3a»), y la primera vez sin el contexto suficiente para decidir: no explicaba qué pasaba con cada opción ni a quién afectaba. Tuve que pedirle que las desarrollara y que dejara de usar letras para algo que no fueran los tramos.
- No había escrito como supuesto que la contabilidad se lleva en Odoo, aunque el tramo B ya dependía de eso al crear un `account.payment`. Salió al conversar el C y quedó como supuesto y como pregunta 11.
- Al escribir la prueba del mensaje de tasa faltante, la fecha del mensaje dependía del idioma del usuario. Se fijó el formato día/mes/año en el código para que el mensaje y la prueba no cambien según el idioma.
- Entregó el tramo sin ejecutar las pruebas en Odoo ni el linter del repositorio. Lo que sigue lo encontró al revisar el tramo contra el enunciado y contra el código de Odoo 18, antes de ejecutar nada:
  - La comprobación de la tasa del día buscaba en la compañía de la solicitud y en las tasas sin compañía, pero Odoo 18 convierte con la tasa de la compañía principal y la prefiere aunque sea más vieja (`res.currency._get_rates`). Odoo solo deja cargar tasas en la compañía principal, así que en una sucursal el pago se habría bloqueado siempre. Y con una tasa sin compañía de ese día más otra de la compañía más vieja, se habría pagado con la vieja sin aviso. Se agregaron dos pruebas y se corrigió.
  - La compañía se podía cambiar en borrador, aunque el número ya llevaba el código de la compañía original.
  - Si alguien quitaba `NOWAIT`, la prueba de concurrencia se habría quedado esperando para siempre en lugar de fallar. Ahora cada conexión tiene un límite de espera y la prueba mide que el aviso sea inmediato.
  - El aviso de tasa faltante y los documentos mandaban a «Contabilidad → Configuración → Monedas»; en Odoo 18 Community es Facturación → Configuración → Contabilidad → Monedas. El comando de pruebas del README estaba mal escrito. `ARCHITECTURE.md` decía que `currency_rate_live` es de Enterprise «en algunas versiones» (no viene en Odoo 18 Community) y no explicaba que, al convertir el error de bloqueo en aviso, se renuncia al reintento automático de Odoo.

## Cómo se verificó (tramo C)

- Las pruebas del tramo C **están pendientes de ejecutar en Odoo**.
- El bloqueo de concurrencia se comprobó en PostgreSQL 16, sin Odoo, con dos conexiones en `REPEATABLE READ`: la segunda recibe el aviso en 0,001 s sin esperar, su transacción sigue usable, y si la primera ya confirmó, PostgreSQL detecta el conflicto.
- Solo se pasó un análisis estático básico con `ruff`. El linter del repositorio (`pylint` con `pylint_odoo`) no estaba instalado.
