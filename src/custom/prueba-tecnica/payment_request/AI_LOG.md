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

- Corrí las pruebas en una base nueva de Odoo 18 con `account` instalado: 47 pruebas del módulo, sin fallos ni errores después de la corrección. Eso confirmó el uso de `account.payment`, `_convert`, `activity_schedule` y el reporte.
- Quedó pendiente por tiempo la prueba a mano en el navegador.
