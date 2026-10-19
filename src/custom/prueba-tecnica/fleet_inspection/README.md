# Inspecciones de vehículos (`fleet_inspection`)

Módulo escrito para Odoo 16 y migrado a Odoo 18 en el ejercicio 2 de la prueba técnica. La migración no cambia lo que hace.

## Qué hace

- Registra inspecciones de los vehículos de Flota con un checklist de puntos (frenos, luces, cauchos…) que se carga solo al crear la inspección.
- Estados: borrador → en curso → aprobada / rechazada. Un punto crítico con falla impide aprobar.
- Tipo de vehículo como campo de selección: moto, carro, camión u otro.
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

## Supuestos y limitaciones

- La versión queda en `18.0.1.0.0`: la migración no cambia el modelo de datos.
- En la 16, `states=` en el campo hacía de solo lectura el vehículo y el tipo en cualquier vista que los mostrara. En la 18 esa regla está en el formulario de este módulo, que es la única vista donde se editan. Una vista nueva que los muestre editables tendría que repetir `readonly="state != 'draft'"`.
- Al crear una inspección, el inspector solo puede elegir vehículos de los que es conductor. El grupo *Inspector* incluye el grupo de usuario de Flota, y Flota tiene la regla `fleet_rule_vehicle_visibility_user` (`[('driver_id', '=', user.partner_id.id)]`). La regla es la misma en Odoo 16 y en 18, así que la migración no cambia este comportamiento. Si el supervisor le asigna una inspección de otro vehículo, el inspector sí puede abrirla e iniciarla. Para que elija cualquier vehículo, hay que ponerlo como conductor o darle un permiso mayor en Flota; se deja como pregunta para el cliente.
- El linter del repositorio marca dos avisos que el módulo ya tenía en la 16: el autor del manifest no es la OCA, y `string="Inspector"` es redundante. No se tocaron para no mezclar mejoras con la migración.
