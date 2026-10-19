# AI_LOG — sale_commission (incidente T-200)

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

1. "Ejercicio 3, tramo A. Reproducir el error con un vendedor, encontrar la causa raíz y corregirla. Empieza por Entender y detente."
   - Hizo el triaje (hotfix), señaló el commit `3f4d73f` como causa probable y me planteó cuatro decisiones. Elegí `sudo()` acotado a la búsqueda en lugar de darle lectura al vendedor, y dejar la regresión de `env.user` como propuesta, no como parte del hotfix.
2. "Hazlo así, tal como lo recomiendas."
   - Escribió primero las pruebas con vendedor y gerente, comprobó que fallaban sin la corrección, aplicó la corrección y escribió `INCIDENT.md`. Lo revisé en el navegador con un vendedor y con el gerente.
3. Tramos B y C: me propuso la contención, los scripts y el plan de datos, y confirmé con cinco ajustes:
   - En la contención, decir que es la misma exposición descartada para la corrección y por qué se acepta un tiempo.
   - Pedirle al gerente que deje de confirmar pedidos ajenos, y crear el permiso con modo desarrollador.
   - Script con la transacción en solo lectura desde la primera instrucción, porcentaje esperado con `order_id.user_id`, y verificar antes que el chatter registra quién confirma.
   - No corregir con *Recalcular comisiones*, y no corregir mientras siga abierta la causa del hallazgo 1.
   - Incluir el script de corrección solo si se prueba con un caso afectado.
4. Mensaje al cliente: la IA hizo un borrador. Al revisar el tramo contra los criterios del enunciado salió que había que acortarlo, poner la hora (8:00 a.m.) y agregar una disculpa. La IA señaló que "mientras tanto" contradecía el INCIDENT y propuso "hasta nuevo aviso". Elegí esa versión final.

## Lo que la IA hizo mal

- Me dijo que en el pedido vería la columna *Comisión* con 16,00. No aparece. Me di cuenta en el navegador; la causa es un xpath que cae en el formulario de la línea y quedó como hallazgo 4.
- Entregó el borrador del mensaje al cliente sin revisarlo contra el enunciado (hora imprecisa, sin disculpa). No lo detectó al entregarlo; apareció en la revisión del tramo contra los criterios del enunciado.
- Usó el prefijo `[ADD]` en un commit, que no está en la lista del enunciado. Apareció en la misma revisión y se cambió a `[FEAT]` antes de subir.
- Las primeras pruebas del script de corrección no probaban lo que decían: un caso alteraba la columna equivocada del CSV y otro corrió sobre un CSV ya vacío. La IA lo vio porque los conteos no cuadraban y las repitió.
- `/code-review` sobre la rama encontró fallas en los scripts que había escrito la IA: incluía en el CSV líneas agregadas después de confirmar, no leía un CSV guardado con Excel en español, podía dejar la corrección a medias si una fila venía mal, y no protegía el CSV contra fórmulas. También encontró que el hallazgo 1 afecta a los pedidos aceptados en el portal (0 %). Se corrigieron los scripts y se volvió a probar todo.
- Casi dio por buena una corrida de pruebas por el código de salida: `./odoo test` devuelve 0 aunque haya pruebas con error. Se detectó leyendo el resumen `... of N tests`.

## Lo que escribí yo sin IA
Partes donde preferí no delegar:
- Las decisiones: atender primero este ticket por ser un incidente en producción, aprobar el
  cambio a "corrección + revisión de datos" en los tramos B y C, y los supuestos de la
  contención y del plan de datos.
- La verificación manual en el navegador como vendedor y como gerente. Ahí encontré que la
  columna Comisión no aparece en las líneas del pedido, algo que las pruebas no detectaban
  (hallazgo fuera del alcance del hotfix, documentado en INCIDENT.md).
- La elección final del mensaje al cliente entre las versiones que propuso la IA.
