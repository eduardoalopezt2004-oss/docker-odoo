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
