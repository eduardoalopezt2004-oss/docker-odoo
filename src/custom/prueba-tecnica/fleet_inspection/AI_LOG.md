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
