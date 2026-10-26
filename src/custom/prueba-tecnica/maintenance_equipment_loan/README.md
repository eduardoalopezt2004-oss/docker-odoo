# Préstamo de equipos (`maintenance_equipment_loan`)

Odoo 18.0. Registra quién se lleva cada equipo de Mantenimiento, para cuándo lo tiene que devolver y cuándo lo devolvió.

## Qué trae Odoo y qué se decidió

| Necesidad | Qué trae Odoo 18 | Salida | Por qué |
|---|---|---|---|
| Quién tiene el equipo | `owner_user_id` en `maintenance.equipment` (`maintenance/models/maintenance.py:143`); `employee_id` en `hr_maintenance` (no instalado) | Propio | Guardan solo el valor actual: el préstamo anterior y su devolución real se pierden |
| Fecha prevista y devolución real | `assign_date` (`maintenance.py:151`), sin fecha prevista ni de devolución | Propio | No hay modelo ni campo de préstamo en el servidor |
| Equipos | `maintenance.equipment` | Tal cual | El préstamo apunta al equipo ya cargado |

Se descartó agregar campos al equipo, porque guardaría solo el préstamo en curso y el historial quedaría sin filtro. También se descartó instalar Empleados (`hr_maintenance`), que no trae fechas de devolución.

## Criterios del tramo A

| # | Criterio | Origen | Evidencia |
|---|---|---|---|
| C1 | El módulo instala sin errores | Tramo A | Instalación en `mantenimiento_vivo` y corrida de pruebas sin errores |
| C2 | Se completa el flujo desde la interfaz | Tramo A | `test_c2_full_flow_as_internal_user` + pasos del navegador |
| C3 | Una devolución prevista anterior a la entrega se bloquea con un mensaje claro | Tramo A | `test_c3_expected_return_before_delivery_is_blocked`, `test_c3_same_day_return_is_allowed` |
| C4 | Cada botón aparece solo en el estado que corresponde | Tramo A | Vista (`invisible`) + `test_c4_each_action_only_in_its_state` para la llamada directa |
| C5 | No se puede devolver un préstamo en borrador | Tramo A | `test_c5_cannot_return_a_draft_loan` |
| C6 | Un borrador se puede eliminar; uno entregado, no | Propuesto | `test_c6_delete_only_a_draft_loan` |
| C7 | Un borrador se puede cancelar (solicitud rechazada); cancelado es estado final | Propuesto | `test_c7_cancel_only_a_draft_loan` |

## Dónde va cada regla

- **Fechas (C3):** `@api.constrains` en el modelo, así se aplica desde la pantalla, por código y al importar.
- **Estados (C4, C5, C7):** cada `action_*` revisa el estado en Python. Ocultar el botón en la vista es solo por comodidad.
- **Eliminar (C6):** `@api.ondelete` en el modelo.

## Seguridad

- Préstamos: acceso total para usuarios internos (`base.group_user`), como pide el enunciado. Eliminar está limitado a borradores en el modelo.
- Mantenimiento solo deja ver a un usuario interno los equipos que sigue (`maintenance.equipment_rule_user`), y así no podría elegir el equipo que presta. El módulo agrega una regla que **solo abre la lectura** de todos los equipos para usuarios internos. Modificar equipos sigue reservado a «Equipment Manager»: lo comprueba `test_internal_user_still_cannot_edit_equipment`. Efecto visible: los usuarios internos también ven todos los equipos en el menú Equipment.

## Cómo probar

Pruebas: `docker exec docker-odoo-odoo-prueba-tecnica-1 odoo -c /home/odoo/.config/odoo.conf -d <base> -u maintenance_equipment_loan --test-tags /maintenance_equipment_loan --stop-after-init --no-http --http-port=38199 --gevent-port=28199`

En el navegador, con el usuario interno `prestamos` (contraseña `prestamos`, sin grupos de Mantenimiento), en la base `mantenimiento_vivo`:

1. **Haz:** Maintenance → **Préstamos** → **New**.
2. **Verifica:** «Recibe» trae tu usuario, «Fecha de entrega» trae hoy y solo aparecen los botones **Entregar** y **Cancelar**.
3. **Haz:** en «Equipo» elige «Laptop Dell Latitude 5440» y en «Devolución prevista» pon ayer. Guarda.
4. **Verifica:** aparece el mensaje «La devolución prevista (…) no puede ser anterior a la fecha de entrega (…)» y no se guarda.
5. **Haz:** cambia «Devolución prevista» a la semana que viene y pulsa **Entregar**.
6. **Verifica:** el estado pasa a «Prestado», ya no están Entregar ni Cancelar y aparece **Devolver**.
7. **Haz:** pulsa **Devolver**.
8. **Verifica:** el estado pasa a «Devuelto», «Devolución real» muestra hoy y no queda ningún botón.

## Supuestos

- La persona que recibe es un usuario de Odoo (`res.users`), como dice el enunciado («por defecto el usuario actual»), y es obligatoria.
- «Anterior» es estricto: devolver el mismo día de la entrega se permite.
- Un equipo con préstamos no se puede borrar (`ondelete="restrict"`).

## Pendiente (siguiente tramo)

- Un equipo no se presta a dos personas a la vez: índice único parcial en la base de datos (`tools.create_unique_index` no acepta condición, `odoo/tools/sql.py:594`).
- Ver rápido los vencidos: campo calculado sin guardar y con búsqueda, como `fleet/models/fleet_vehicle.py:102`, más un filtro.
- Fuera de borrador, los campos quedan de solo lectura en la vista, pero el modelo todavía no lo impide si se escribe por código.
- Si la fecha de entrega es futura y se devuelve hoy, la devolución real queda antes de la entrega: no se valida.
