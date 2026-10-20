# Inspecciones de vehículos (`fleet_inspection`)

Módulo escrito para Odoo 16 y migrado a Odoo 18 en el ejercicio 2 de la prueba técnica. La migración (tramo A) no cambia lo que hace. En el tramo B el tipo de vehículo pasó de una lista fija a un catálogo, con un script que conserva el tipo de las inspecciones existentes.

## Tramos

- [x] A: migración de Odoo 16 a 18 (versión `18.0.1.0.0`).
- [x] B: tipo de vehículo como catálogo, con script de migración de datos (versión `18.0.1.1.0`).
- [x] C: migración por lotes e idempotente, ensayo medido con 10.000 inspecciones y `MIGRATION_PLAN.md` con sus pasos probados (ver [Ensayo con 10.000 inspecciones](#ensayo-con-10000-inspecciones)).

## Qué hace

- Registra inspecciones de los vehículos de Flota con un checklist de puntos (frenos, luces, cauchos…) que se carga solo al crear la inspección.
- Estados: borrador → en curso → aprobada / rechazada. Un punto crítico con falla impide aprobar.
- Tipo de vehículo elegido de un catálogo que administra el supervisor en Flota → Configuración → Tipos de vehículo. Viene con Moto, Carro, Camión y Otro.
- Grupos: *Inspector* (ve solo sus inspecciones) y *Supervisor de inspecciones* (ve todas, aprueba y rechaza).
- Acción planificada diaria que marca las inspecciones con más de 7 días en curso y le crea una actividad al inspector.
- Reporte PDF de la inspección.

## Cómo probarlo (Odoo 18)

```bash
./odoo test -i prueba-tecnica -d <base_nueva> -m fleet_inspection
```

El comando termina con código 0 aunque haya pruebas con error: hay que leer la línea `... of N tests` del final.

## Migración de Odoo 16 a Odoo 18 (tramo A)

| Qué cambió | Por qué | Cómo lo resolví |
|---|---|---|
| Ubicación del módulo | Estaba en `src/custom/prueba-tecnica-odoo16/`, fuera del directorio de addons, porque con su versión 16.0 impedía arrancar Odoo 18 | Se movió a `src/custom/prueba-tecnica/` en un commit que solo mueve archivos |
| `version` del manifest | Odoo 18 exige versiones `18.0.x.y.z`; con `16.0.1.0.0` lanza `ValueError` al leer el manifest | `18.0.1.0.0`, conservando el `1.0.0` del módulo |
| `states=` en los campos `vehicle_id` y `vehicle_type` | El parámetro no existe desde la 17: Odoo avisa `unknown parameter 'states'` y el campo queda de solo lectura siempre, también en borrador | Se quitaron `readonly=True` y `states` del campo, y el formulario tiene `readonly="state != 'draft'"`. En la 16 `states` solo afectaba a la vista, así que el comportamiento es el mismo |
| `create` con `@api.model` | Odoo 18 avisa que el modelo no crea en lote (`is not overriding the create method in batch`) | `@api.model_create_multi` y un bucle sobre `vals_list`, con la misma lógica para cada registro |
| `name_get` | Desde la 17 Odoo no lo llama, y el nombre mostrado habría perdido la placa | `_compute_display_name` con `@api.depends` en el número y en la placa o nombre del vehículo. El texto es el mismo |
| `<tree>` y `view_mode` `tree` | En 18 el tipo de vista se llama `list` | `<list>` en las tres vistas de lista y `list` en las dos acciones |
| `states=` en los botones | Desde la 17 Odoo rechaza la vista ("Since 17.0, the "attrs" and "states" attributes are no longer used") | `invisible="state != '…'"` con los mismos estados que antes |
| `attrs` en el aviso de vencida, el kilometraje, la fecha, el checklist y el resultado | El mismo rechazo de la fila anterior | Atributos `invisible`, `readonly` y `required` con la expresión equivalente |
| `invisible="1"` en columnas de lista | Desde la 17, en una lista `invisible` oculta el valor de la celda, pero la columna queda visible | `column_invisible="1"`. Los campos siguen en la vista porque los usan `decoration-warning` y `required` |
| Chatter con `<div class="oe_chatter">` | Odoo 18 usa la etiqueta `<chatter/>`, como el propio módulo `fleet` | `<chatter/>` |
| `numbercall` y `doall` en la acción planificada | Esos campos no existen en `ir.cron` de 18 y la carga del XML falla | Se quitaron. El intervalo diario y el código no cambian |
| `t-esc` en el reporte | Odoo 18 lo marca como obsoleto ("Found deprecated directive @t-esc… Replace by @t-out") | `t-out`, que escapa el texto igual |
| `from odoo.tests.common import Form` | Odoo 18 lo marca como obsoleto ("odoo.tests.common.Form is deprecated, use odoo.tests.Form") | `from odoo.tests import Form, TransactionCase, tagged` |
| Prueba `test_name_get_includes_plate` | Usaba `name_get()`, que ya no existe | Se renombró a `test_display_name_includes_plate` y comprueba `display_name` |
| Pruebas nuevas `test_display_name_same_format_as_name_get` y `test_vehicle_editable_only_in_draft` | Lo que pasó de `name_get` y de `states=` a otro lugar no tenía prueba: si se perdía, las pruebas seguían pasando | La primera compara el texto exacto (número - placa, o número - nombre si no hay placa). La segunda edita el tipo en borrador y espera solo lectura en curso. Se comprobó que falla si se quita el `readonly` del formulario |
| Descripción del módulo (`static/description/index.html`, archivo nuevo) | Sin ese archivo, Odoo 18 lee el README como reStructuredText al instalar, y la tabla de esta sección deja tres mensajes de docutils en el registro (`(WARNING/2)` y `(ERROR/3)` en la línea 25) | Una descripción corta en HTML. Odoo la muestra en Aplicaciones y ya no procesa el README |

No cambiaron, porque siguen siendo válidos en 18: los grupos, reglas de registro y permisos; los menús; la secuencia y los puntos del checklist; la vista de búsqueda; `_sql_constraints`.

## Cómo se verificó

- Pruebas en una base nueva: `0 failed, 0 error(s) of 11 tests`.
- Instalación en una base nueva (`odoo -i fleet_inspection --log-level=info`): el registro no tiene `WARNING`, `ERROR` ni avisos de obsolescencia del logger, ni mensajes de docutils de este módulo. Quedan dos mensajes de docutils (`<string>:38: (ERROR/3)` y `<string>:43: (WARNING/2)`) que salen al cargar el módulo `mail` de Odoo, antes de que empiece `fleet_inspection`.
- En esa base, desde `odoo shell` y deshaciendo todo al final:
  - El nombre mostrado incluye la placa.
  - El reporte se genera con la placa y el checklist.
  - El tipo de vehículo se edita en borrador; en curso, el vehículo y el tipo son de solo lectura.
  - Las vistas de lista y formulario cargan.
  - No se registró ningún aviso.

## Tipo de vehículo como catálogo (tramo B, versión 18.0.1.1.0)

El campo `vehicle_type` pasó de selección fija a many2one al modelo nuevo `fleet.inspection.vehicle.type`. La convención de Odoo sería `vehicle_type_id`; se conservó `vehicle_type` para no cambiar vistas, reporte, filtros ni referencias externas.

- Catálogo con nombre (traducible) y activo. Lo lee el inspector y lo administra el supervisor en Flota → Configuración → Tipos de vehículo. En la inspección solo se elige un tipo existente.
- Carro sigue siendo el tipo por defecto. Un tipo en uso no se puede borrar.
- Los cuatro tipos iniciales se cargan con `noupdate`: si el cliente les cambia el nombre, una actualización no lo pisa.

### Cómo se conservan los datos viejos

Al subir la versión a `18.0.1.1.0`, Odoo ejecuta los scripts de `migrations/18.0.1.1.0/`. La lógica está en `tools/vehicle_type_migration.py`, para poder probarla sin actualizar una base.

1. Antes de que Odoo cambie la tabla (`pre-migrate.py`), la columna de texto `vehicle_type` se renombra a `vehicle_type_legacy`, con sus valores intactos. Hace falta porque, si la columna conservara su nombre, Odoo intentaría convertir `'car'` en un número y la actualización fallaría. Con un nombre de campo nuevo, Odoo borraría la columna vieja al terminar. Ningún campo usa `vehicle_type_legacy`, así que Odoo no la toca. Si la columna ya fue renombrada o ya es el many2one, el script no hace nada.
2. Odoo crea la columna nueva `vehicle_type` y carga el catálogo. Las inspecciones existentes quedan con el tipo vacío.
3. Después de cargar el catálogo (`post-migrate.py`), cada inspección sin tipo recibe el del catálogo que corresponde a su valor viejo:

| Valor viejo (`vehicle_type_legacy`) | Tipo del catálogo | Identificador |
|---|---|---|
| `motorcycle` | Moto | `fleet_inspection.vehicle_type_motorcycle` |
| `car` | Carro | `fleet_inspection.vehicle_type_car` |
| `truck` | Camión | `fleet_inspection.vehicle_type_truck` |
| `other` | Otro | `fleet_inspection.vehicle_type_other` |

4. El mismo script verifica el resultado. Si hay un valor viejo que no está en la tabla, o si al final queda alguna inspección sin tipo, el script detiene la actualización con un mensaje que dice cuántas son. La actualización se deshace completa y la base queda como estaba.

El script solo completa tipos vacíos: ejecutarlo otra vez no cambia nada ni deshace un tipo que alguien cambió después de migrar. La columna `vehicle_type_legacy` se conserva como respaldo. Borrarla queda para una versión posterior, después de verificar los datos en producción.

### Actualizar una base con datos

Para la base de un cliente, el procedimiento completo, con respaldo verificado, verificación previa y posterior y reversión, está en [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md). Resumen:

1. Respaldo: `pg_dump -Fc <base> -f antes.dump`.
2. Conteo antes: `SELECT vehicle_type, count(*) FROM fleet_inspection GROUP BY 1;`
3. Actualizar con el código nuevo: `odoo -d <base> -u fleet_inspection --stop-after-init`. En el registro aparece `Tipo de vehículo migrado: N inspecciones recibieron su tipo del catálogo`, con el detalle por valor viejo.
4. Conteo después, que debe coincidir con el paso 2 y no tener filas sin tipo:

   ```sql
   SELECT f.vehicle_type_legacy, t.name->>'en_US' AS tipo, count(*)
     FROM fleet_inspection f
     LEFT JOIN fleet_inspection_vehicle_type t ON t.id = f.vehicle_type
    GROUP BY 1, 2 ORDER BY 1;
   ```

### Cómo se verificó (tramo B)

- Pruebas en una base nueva: `0 failed, 0 error(s) of 22 tests`. Son las 11 del tramo A adaptadas al catálogo, 2 del catálogo (quién lo lee y quién lo modifica, y que un tipo en uso no se borra) y 9 de la lógica de migración, en `tests/test_vehicle_type_migration.py`:
  - el mapeo de los cuatro valores, incluido «otro»;
  - una segunda ejecución no cambia nada y no deshace un tipo cambiado después de migrar;
  - un valor desconocido, una inspección sin ningún tipo y la falta del respaldo detienen la migración;
  - las inspecciones nuevas no se tocan;
  - el pre-migrate renombra una sola vez una columna `varchar` o `text`, y no hace nada si ya es many2one.
- Antes del código, la carga de las pruebas se detenía porque no existía `tools/vehicle_type_migration.py`. Las tres pruebas agregadas después de la revisión de código fallaban con la lógica anterior (`3 failed of 22`).
- Prueba en el navegador automatizada por la IA del formulario con el tipo de vehículo como catálogo. Después la revisé en el navegador para confirmar.
- Escenario real:
  1. Base nueva con la versión `18.0.1.0.0` y 11 inspecciones: 3 motos, 4 carros, 2 camiones y 2 «otro», en borrador, en curso, aprobadas y rechazadas.
  2. Respaldo con `pg_dump`.
  3. Código `18.0.1.1.0` y `-u fleet_inspection`: 14 s, sin avisos en el registro.

| Valor viejo | Tipo después de actualizar | Inspecciones |
|---|---|---|
| `car` | Carro | 4 |
| `motorcycle` | Moto | 3 |
| `other` | Otro | 2 |
| `truck` | Camión | 2 |

  Ninguna inspección quedó sin tipo ni con un tipo distinto al de su valor viejo. `vehicle_type_legacy` es idéntica, fila por fila, al listado tomado antes de actualizar, y `vehicle_type` quedó como obligatoria en la base (`NOT NULL`).
- Linter del repositorio: solo los dos avisos que el módulo ya tenía (autor OCA y `string="Inspector"`).

## Migración por lotes, idempotente y ensayada (tramo C)

### Qué cambió en la migración

- **Por lotes.** El `post-migrate` recorre las inspecciones sin tipo en orden de id, de a 1.000 (`DEFAULT_BATCH_SIZE` en `tools/vehicle_type_migration.py`). Cada lote se delimita con una consulta que devuelve solo el último id del lote, y cada `UPDATE` toca a lo sumo 1.000 filas. Python guarda solo ese último id, así que la memoria no crece con el tamaño de la tabla. La paginación por id funciona aunque haya huecos en los ids y salta las inspecciones que ya tienen tipo.
- **Una sola transacción.** Los lotes no confirman por separado: toda la actualización sigue en la transacción de `-u`. Así, si algo falla, Odoo deshace todo y la base queda en `18.0.1.0.0`. Los lotes acotan cada sentencia y dan avance en el registro cada 10 lotes, pero las filas quedan bloqueadas hasta el final de la actualización (ver [Supuestos y limitaciones](#supuestos-y-limitaciones)).
- **Idempotente.** Ya lo era en el tramo B: el `pre-migrate` no renombra dos veces y el `post-migrate` solo completa tipos vacíos. En el tramo C se prueba también con lotes, y el ensayo lo comprueba con la base real, haciendo que Odoo ejecute la migración por segunda vez.
- **Medible.** La línea final del registro dice cuántas inspecciones recibieron tipo, en cuántos lotes, en cuántos segundos y la memoria máxima del proceso, por ejemplo: `Tipo de vehículo migrado: <N> inspecciones recibieron su tipo del catálogo, en <L> lotes de hasta 1000, en <S> s; memoria máxima del proceso: <M> MB`.
- La versión sigue en `18.0.1.1.0`: el tramo C mejora el mismo script de migración antes de que llegue a producción. Una base que ya se actualizó con la versión del tramo B no lo vuelve a ejecutar, y tampoco lo necesita.

### Scripts de ensayo

En `scripts/`, para correr con `odoo shell`. El módulo no los carga:

- `generate_legacy_inspections.py`: crea inspecciones de prueba en una base con la versión `18.0.1.0.0`, con el checklist completo y reparto fijo por tipo (moto 30 %, carro 40 %, camión 20 %, otro 10 %) y por estado. Usa una semilla, así que con la misma semilla salen los mismos datos. Confirma cada 500 y vacía la caché. Se niega a correr si el tipo ya es el catálogo.
- `check_vehicle_types.py`: solo lectura. Cuenta las inspecciones por tipo antes y después de actualizar, y las que quedaron sin tipo. Es la verificación previa y posterior de `MIGRATION_PLAN.md`.

### Ensayo con 10.000 inspecciones

Se hace en una base desechable, en la máquina donde corre la instancia. Desde la raíz del repositorio, con el código que trae este tramo y sin cambios sin guardar:

```bash
BASE=fleet_ensayo
SVC="docker compose -f docker-compose.generated.yml exec -T odoo-prueba-tecnica"
DB="docker compose -f docker-compose.generated.yml exec -T db-pg16"
FS=/home/odoo/data/filestore
NUEVO=$(git rev-parse HEAD)   # commit con el tramo C, para volver en el paso 6

# 1. Copiar los scripts fuera del repositorio: el paso 2 cambia el código.
cp src/custom/prueba-tecnica/fleet_inspection/scripts/generate_legacy_inspections.py /tmp/
cp src/custom/prueba-tecnica/fleet_inspection/scripts/check_vehicle_types.py /tmp/
mkdir -p ~/ensayo_respaldo

# 2. Código con la versión 18.0.1.0.0 (último commit antes del tramo B del ejercicio 2).
git switch --detach fb39197
./odoo restart prueba-tecnica

# 3. Base nueva con el módulo en 18.0.1.0.0, sin datos de demostración.
time $SVC odoo -d $BASE -i fleet_inspection --without-demo=all --stop-after-init --http-port 9999 --workers=0

# 4. Generar 10.000 inspecciones (medido) y contar.
time $SVC odoo shell -d $BASE --no-http < /tmp/generate_legacy_inspections.py 2>&1 | tee ~/ensayo_1_generacion.log
$SVC odoo shell -d $BASE --no-http < /tmp/check_vehicle_types.py 2>&1 | tee ~/ensayo_2_antes.txt

# 5. Respaldo de la base y del filestore (medido), como en producción.
time { $DB pg_dump -U odoo -Fc -d $BASE > ~/ensayo_respaldo/$BASE.dump \
  && $SVC tar czf - -C $FS $BASE > ~/ensayo_respaldo/filestore.tgz; }

# 6. Código nuevo y actualización (medido).
git switch --detach $NUEVO
time ./odoo update prueba-tecnica -d $BASE -m fleet_inspection 2>&1 | tee ~/ensayo_3_actualizacion.log
grep -E "Tipo de vehículo migrado|No se puede migrar|ERROR|CRITICAL" ~/ensayo_3_actualizacion.log
$SVC odoo shell -d $BASE --no-http < /tmp/check_vehicle_types.py 2>&1 | tee ~/ensayo_4_despues.txt

# 7. Segunda ejecución de la migración: se le dice a Odoo que el módulo sigue en
#    18.0.1.0.0 y se actualiza otra vez, así vuelve a correr pre-migrate y post-migrate.
echo "env.cr.execute(\"UPDATE ir_module_module SET latest_version = '18.0.1.0.0' WHERE name = 'fleet_inspection'\"); env.cr.commit()" | $SVC odoo shell -d $BASE --no-http
time ./odoo update prueba-tecnica -d $BASE -m fleet_inspection 2>&1 | tee ~/ensayo_5_segunda.log
grep -E "Tipo de vehículo migrado|ERROR|CRITICAL" ~/ensayo_5_segunda.log
$SVC odoo shell -d $BASE --no-http < /tmp/check_vehicle_types.py 2>&1 | tee ~/ensayo_6_despues_segunda.txt

# 8. Restaurar el respaldo del paso 5 en otra base (medido) y contar: debe dar lo mismo que el paso 4.
R=${BASE}_restaurada
time { $DB createdb -U odoo $R \
  && $DB pg_restore -U odoo -d $R --no-owner < ~/ensayo_respaldo/$BASE.dump \
  && $SVC sh -c "mkdir -p $FS/$R && tar xzf - -C $FS/$R --strip-components=1" < ~/ensayo_respaldo/filestore.tgz; }
$SVC odoo shell -d $R --no-http < /tmp/check_vehicle_types.py
```

Qué se espera:

| Paso | Esperado |
|---|---|
| 4 | `Listo: 10000 inspecciones`; reparto aproximado 3.000 motos, 4.000 carros, 2.000 camiones y 1.000 «otro» |
| 6 | `Tipo de vehículo migrado: 10000 inspecciones … en 10 lotes de hasta 1000`; ningún `ERROR`; en `ensayo_4_despues.txt`, cada valor viejo con el mismo conteo que en `ensayo_2_antes.txt` y `Inspecciones sin tipo (debe ser 0): 0` |
| 7 | `Tipo de vehículo migrado: 0 inspecciones … en 0 lotes`; `ensayo_6_despues_segunda.txt` igual a `ensayo_4_despues.txt` |
| 8 | Igual que `ensayo_2_antes.txt` |

### Resultado del ensayo

Medido el 2026-10-20 con los pasos de arriba, en un portátil: Intel Core i5-7300U (4 hilos, 2,6 GHz), 7,7 GB de memoria para WSL 2 y Docker, disco virtual de WSL 2 (ext4), PostgreSQL 16.15 y Odoo 18.0 de la imagen del repositorio. En el servidor del cliente los tiempos serán otros: por eso el plan pide repetir el ensayo en una copia de su base.

| Medición | Resultado |
|---|---|
| Instalar el módulo en `18.0.1.0.0` en una base nueva (paso 3) | 48,1 s |
| Generar 10.000 inspecciones con su checklist, 50.000 líneas (paso 4) | 40,9 s (el script: 37,8 s, 264 por segundo; memoria máxima 136 MB) |
| Respaldo: base de 2,4 MB y filestore de 0,9 MB (paso 5) | 1,4 s |
| Actualización completa con `./odoo update` (paso 6) | 8,8 s |
| Migración del tipo, según el registro (paso 6) | 0,29 s: 10.000 inspecciones en 10 lotes de 1.000 |
| Memoria máxima del proceso de actualización (paso 6) | 131 MB |
| Segunda actualización (paso 7) | 8,0 s: 0 inspecciones en 0 lotes |
| Restauración en otra base (paso 8) | 28,5 s |

Conteos: antes de actualizar, 4.096 `car`, 2.941 `motorcycle`, 2.008 `truck` y 955 `other`. Después, cada valor con el mismo conteo y su tipo (`car -> Carro`, `motorcycle -> Moto`, `truck -> Camión`, `other -> Otro`) y 0 inspecciones sin tipo. La segunda actualización dejó los conteos iguales, y la base restaurada dio los mismos conteos que antes de actualizar y los mismos 162 archivos del filestore.

El ensayo completo se corrió tres veces. En las dos primeras falló el respaldo (ver [Supuestos y limitaciones](#supuestos-y-limitaciones)) y la migración del tipo tardó 0,22 s y 0,27 s. La tabla es de la tercera corrida, que hizo todos los pasos.

### Cómo se verificó (tramo C)

- Pruebas en una base nueva: `0 failed, 0 error(s) of 29 tests`. Son 7 pruebas nuevas en `tests/test_vehicle_type_migration.py`:
  - lotes de 1 dan lo mismo que uno solo;
  - 33 inspecciones en lotes de 7 son 5 lotes y ninguna queda sin tipo;
  - una fila con tipo dentro de un lote no se toca;
  - una segunda ejecución por lotes no cambia nada («0 lotes»);
  - un tamaño de lote 0 o negativo se rechaza antes de tocar datos;
  - el registro trae el tiempo y la memoria.
- La primera ejecución en Odoo dio `1 failed of 29`: la prueba de lotes creaba 25 inspecciones nuevas en lugar de las 29 que dice su descripción. Era un error de la prueba, no de la migración; se corrigió y la prueba ahora verifica la cantidad.
- Para saber que las pruebas no pasan de casualidad, se rompió el código a propósito dos veces:
  - sin límite superior del lote falló la prueba de los 5 lotes;
  - con el `UPDATE` sin la condición de tipo vacío falló la de la fila que ya tenía tipo.
- Linter del repositorio: solo los dos avisos que el módulo ya tenía.
- Las dos reversiones de `MIGRATION_PLAN.md` se probaron en la base del ensayo:
  - **A.** Con una inspección con el valor `van`, la actualización se detuvo con «No se puede migrar el tipo de vehículo: hay inspecciones con valores que no tienen destino en el catálogo (van: 1)» y la base quedó igual, en `18.0.1.0.0`.
  - **B.** Restaurar el respaldo sobre la base ya migrada tardó 37,2 s y la dejó igual que antes de actualizar.
- Verificación en el navegador, en la base restaurada del ensayo y migrada (10.000 inspecciones): la columna *Tipo de vehículo* llena en la lista, el agrupado por tipo con los mismos conteos del ensayo, tres inspecciones antiguas (aprobada, borrador y rechazada) con su vehículo y su tipo, y el catálogo en *Configuration → Tipos de vehículo*.
- Antes de correr Odoo, el SQL de los lotes ya se había probado solo en PostgreSQL 16, sobre una tabla de 10.000 filas con un hueco de 500 ids y una fila con tipo: asignó tipo a las 9.499 pendientes en 10 lotes, no tocó la fila con tipo y la segunda ejecución dio 0 filas.

## Supuestos y limitaciones

- Tramo A: la versión queda en `18.0.1.0.0`, porque la migración no cambia el modelo de datos. Tramo B: `18.0.1.1.0`, porque el tipo de vehículo cambia de selección a catálogo.
- Desde `18.0.1.1.0`, quien lea `vehicle_type` desde otro sistema (por ejemplo, por RPC) recibe un registro del catálogo y no el texto `'car'`.
- Un valor viejo sin destino en el catálogo detiene la actualización en lugar de mandarlo a «Otro»: así ninguna inspección queda con un tipo equivocado sin aviso.
- Tramo C: los lotes no confirman por separado. La migración entera es una transacción, para que un fallo la deshaga completa. Con 10.000 inspecciones no es un problema, pero las filas quedan bloqueadas hasta que termina la actualización, por eso el plan pide que nadie use Odoo durante la ventana. Para tablas de millones de filas habría que evaluar confirmar por lotes fuera de `-u`, y eso pierde la reversión automática.
- Tramo C: el respaldo y la restauración usan `pg_dump`, `pg_restore` y una copia del filestore con `tar`, no el script `scripts/odoo_backup` del repositorio. Ese script falla en este entorno al generar el volcado: pasa el puerto de la base como número a `shlex.quote`, que solo acepta texto (`TypeError` en la línea 279). Como `./odoo restore` espera el `.zip` que produce ese script, tampoco se usa. El script es del repositorio y no se modificó.
- Tramo C: el lote de 1.000 es un valor fijo en el código. No se expuso como parámetro porque con este volumen no cambia el resultado; se ajusta en `DEFAULT_BATCH_SIZE` si una base lo necesitara.
- En la 16, `states=` en el campo hacía de solo lectura el vehículo y el tipo en cualquier vista que los mostrara. En la 18 esa regla está en el formulario de este módulo, que es la única vista donde se editan. Una vista nueva que los muestre editables tendría que repetir `readonly="state != 'draft'"`.
- Al crear una inspección, el inspector solo puede elegir vehículos de los que es conductor. El grupo *Inspector* incluye el grupo de usuario de Flota, y Flota tiene la regla `fleet_rule_vehicle_visibility_user` (`[('driver_id', '=', user.partner_id.id)]`). La regla es la misma en Odoo 16 y en 18, así que la migración no cambia este comportamiento. Si el supervisor le asigna una inspección de otro vehículo, el inspector sí puede abrirla e iniciarla. Para que elija cualquier vehículo, hay que ponerlo como conductor o darle un permiso mayor en Flota; se deja como pregunta para el cliente.
- El linter del repositorio marca dos avisos que el módulo ya tenía en la 16: el autor del manifest no es la OCA, y `string="Inspector"` es redundante. No se tocaron para no mezclar mejoras con la migración.
