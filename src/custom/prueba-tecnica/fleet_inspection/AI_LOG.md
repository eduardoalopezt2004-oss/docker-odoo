# AI_LOG — fleet_inspection (migración de Odoo 16 a 18)

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

1. "Ejercicio 2, tramo A ... Primero el inventario completo ... No toques nada hasta que lo apruebe. Cero mejoras de lógica."
   - Hizo el inventario de lo que había que cambiar de Odoo 16 a 18, con cada punto verificado en el código de Odoo 18: 15 cambios y la lista de lo que no cambia. Lo aprobé con cuatro decisiones: la rama sale sin la corrección de T-200, la versión queda en `18.0.1.0.0`, la prueba de `name_get` se renombra y aparece en la tabla del README, y los commits no esperan mi aprobación.
2. Migración y revisión, después de aprobar el inventario.
   - Primero movió el módulo en un commit que solo mueve archivos. Después migró el manifest, el Python, las vistas, la acción planificada, el reporte y las pruebas, y comprobó que la seguridad y los menús siguen siendo válidos sin cambios.
   - Pasó `/code-review`, que dio 8 hallazgos. Se corrigieron 2, se documentó 1 y, a partir de otros 2, se agregaron pruebas para lo que cambió de lugar (`name_get` y `states=`). Para saber que la prueba de solo lectura sirve, la IA quitó a propósito el `readonly` del formulario y la prueba falló. Los últimos 3 eran mejoras de lógica y no se aplicaron, por la regla de no mejorar nada en la migración.

## Lo que la IA hizo mal

- Revisó los avisos de la instalación buscando solo `WARNING` y dio el registro por limpio. Los mensajes de docutils tienen otro formato (`(ERROR/3)`) y no aparecían en esa búsqueda. La tabla nueva del README los provocaba, y el README decía "sin avisos". Lo detectó `/code-review`. Se agregó `static/description/index.html` para que Odoo no procese el README, y se corrigió la verificación. En la corrección de T-200 la IA ya había pasado por alto un mensaje de ese tipo sin averiguar de dónde salía (era del módulo `mail` de Odoo).
- Los pasos para probar en el navegador pedían que el inspector eligiera el vehículo AB123CD sin comprobar antes que podía verlo. La regla de Flota solo le muestra al inspector los vehículos de los que es conductor. Lo encontré en el navegador. La IA verificó que la regla es la misma en Odoo 16, así que no viene de la migración, y quedó como limitación en el README.

## Lo que escribí yo sin IA

Partes donde preferí no delegar:

- Las decisiones de la migración: ninguna mejora de lógica, la rama sin la corrección de T-200, la versión `18.0.1.0.0` y renombrar la prueba de `name_get` mostrándola en la tabla del README. Por la regla de no mejorar la lógica quedaron fuera tres hallazgos de la revisión de código.
- La verificación en el navegador como inspector y como supervisor: el checklist al guardar, el solo lectura al iniciar, el bloqueo de Aprobar con un punto crítico fallido, el rechazo, la configuración del checklist y el reporte PDF. Ahí encontré que el inspector solo puede elegir vehículos de los que es conductor; lo resolví poniéndolo como conductor y quedó como limitación en el README.

---

# Tramo B — tipo de vehículo como catálogo y script de migración

## Prompts clave (tramo B)

1. "Ejercicio 2, tramo B ... el tipo de vehículo pasa a ser un catálogo ... Escribe el script en migrations/ ... Empieza por Entender y detente."
   - La IA mostró, verificado en el código de Odoo 18, por qué cambiar el campo sin preparar la base pierde los datos: con el mismo nombre la actualización falla al convertir el texto, y con un nombre nuevo Odoo borra la columna vieja. Propuso guardar la columna con un `pre-migrate` y mapear los cuatro valores en el `post-migrate`.
2. Aprobé el plan con mis decisiones (abajo) y siguió con las pruebas primero.

## Qué decidí yo (tramo B)

- Conservar el nombre `vehicle_type` para no cambiar vistas, reporte, filtros ni referencias externas. La convención de Odoo sería `vehicle_type_id`, y así quedó escrito en el README.
- Que un valor anterior desconocido detenga la actualización en lugar de mandarlo a «Otro», porque eso le pondría un tipo equivocado sin avisar.
- Conservar la columna anterior como respaldo para verificar y revertir.
- Que el catálogo lo administre solo el supervisor y que sus nombres no se pisen al actualizar.

## Lo que la IA hizo mal (tramo B)

- `/code-review` encontró casos que la lógica de migración no cubría. Se agregaron tres pruebas que fallaban con la lógica anterior (`3 failed of 22`) y se corrigió: la migración solo completa tipos vacíos y nunca deja inspecciones sin tipo.

## Cómo se verificó (tramo B)

- Pruebas en una base nueva: 22 pruebas del módulo, sin fallos ni errores, 9 de ellas de la lógica de migración.
- Prueba en el navegador automatizada por la IA del formulario con el tipo de vehículo como catálogo. Después la revisé en el navegador para confirmar.

---

# Tramo C — migración por lotes, idempotente y ensayada

## Prompts clave (tramo C)

Resúmenes, no citas textuales:

1. Seguir con el tramo C del ejercicio 2 con la misma metodología: pruebas primero, commits por tipo y documentación al final, en una rama propia y sin integrar.
   - La IA no empezó hasta tener el tramo B en el repositorio: el C modifica su script de migración, y escribirlo sin verlo habría sido adivinar nombres.
   - Con el B integrado, propuso el plan: lotes por id dentro de la transacción de `-u`, generador de 10.000 inspecciones en `18.0.1.0.0`, segunda ejecución real volviendo la versión del módulo a `18.0.1.0.0`, y `MIGRATION_PLAN.md`.
2. Aprobé el plan.
3. Terminar el tramo C: correr las pruebas en Odoo, hacer el ensayo con 10.000 inspecciones e integrarlo.
   - Decidí rebasar la rama sobre la principal en lugar de un merge, porque todavía no se había revisado.
   - La IA corrió las pruebas, el ensayo completo y las dos reversiones del plan, y corrigió lo que falló (abajo).

## Qué decidió la IA y aprobé (tramo C)

- Mantener la versión `18.0.1.1.0`: el C mejora el mismo script antes de que llegue a producción.
- Lotes de 1.000 sin confirmar por separado, para no perder la reversión automática de Odoo si la migración falla. El costo, que las filas quedan bloqueadas hasta el final, está en el README y el plan pide no usar Odoo durante la ventana.
- Paginación por id (cada lote se delimita por el último id procesado) en lugar de rangos fijos de id, para que funcione con huecos y no recorra rangos vacíos.
- Probar la idempotencia con la base real, haciendo que Odoo ejecute la migración por segunda vez, además de las pruebas automáticas.
- La reversión estándar es restaurar el respaldo, no deshacer la columna en la misma base, porque ese camino no está probado.

## Lo que la IA hizo mal (tramo C)

- En la prueba de lotes, al releerla antes de escribir el código, cambió el resultado esperado de 29 a 33 (las 4 inspecciones de la preparación de la clase también quedan sin tipo), pero no la cantidad de inspecciones nuevas: la lista armaba 25, no 29. La primera ejecución en Odoo dio `1 failed of 29` (29 en lugar de 33). La IA reprodujo la preparación en una base aparte para descartar un fallo de la migración y corrigió la prueba, que ahora verifica la cantidad.
- Escribió en el README y en `MIGRATION_PLAN.md` comandos de respaldo y restauración sin ejecutarlos: a `scripts/odoo_backup` le faltaba un argumento obligatorio y, con él, el script del repositorio falla igual (`TypeError` al armar el comando de `pg_dump`). `./odoo restore` y `./odoo psql remove` tampoco se habían probado. Apareció en el ensayo: el respaldo no se hizo. Se pasó a `pg_dump`, `pg_restore`, `dropdb` y `tar`, y se repitió el ensayo completo.
- La primera versión del `UPDATE` por lotes armaba el SQL con `%`. No había riesgo real (solo marcadores fijos), pero el linter de Odoo lo marca como posible inyección. Se cambió por `odoo.tools.SQL`.
- El plan de migración mostraba una línea de registro de ejemplo con tiempos y memoria inventados. Como el criterio pide tiempos medidos y no supuestos, se cambió por marcadores (`<S> s`, `<M> MB`).

## Cómo se verificó (tramo C)

- Pruebas en una base nueva: `0 failed, 0 error(s) of 29 tests`. Para saber que no pasan de casualidad, la IA rompió el código dos veces (sin límite del lote y sin la condición de tipo vacío) y cada vez falló la prueba que lo cubre.
- Linter del repositorio: solo los dos avisos que el módulo ya tenía.
- Ensayo con 10.000 inspecciones con los pasos del README: la migración asignó su tipo a las 10.000 en 10 lotes, en 0,29 s; la segunda ejecución no cambió nada y la base restaurada dio los mismos conteos. Los tiempos están en el README y en `MIGRATION_PLAN.md`.
- Las dos reversiones del plan, probadas en la base del ensayo: una actualización que falla deja la base igual, y restaurar el respaldo sobre la base migrada la deja como antes.
- Verifiqué en el navegador la base del ensayo, restaurada y migrada con las 10.000 inspecciones: el tipo en la lista, el agrupado por tipo con los conteos del ensayo, tres inspecciones antiguas en estados distintos con su tipo y el catálogo de tipos.
