# Solicitudes de pago (`payment_request`)

Ejercicio 4 de la prueba técnica. Hoy las solicitudes de pago a proveedores llegan por WhatsApp y nadie sabe cuáles se aprobaron. Con este módulo cualquier empleado pide el pago en Odoo, y el chatter de cada solicitud guarda quién la envió, quién la aprobó y quién la pagó.

## Tramos

- [x] A: modelo, flujo de estados, grupos, vistas y menú.
- [x] B: niveles de aprobación por monto, aprobador asignado, rechazo con motivo, pago con `account.payment` y reporte PDF.
- [ ] C: no iniciado.

## Qué hace (tramo A)

- Modelo `payment.request` con número (`SP/2026/0001`), proveedor, solicitante, monto, moneda, fecha, concepto y estado.
- Estados: borrador → enviada → aprobada → pagada. Desde enviada también se puede rechazar.
- Tres grupos, en Ajustes → Usuarios, categoría «Solicitudes de pago»:

| Grupo | Ve | Puede |
|---|---|---|
| Solicitante (todo usuario interno) | Sus solicitudes | Crear, editar y borrar en borrador; enviar |
| Aprobador | Todas | Aprobar o rechazar las enviadas; no puede aprobar las propias |
| Tesorería | Todas | Marcar como pagadas las aprobadas |

- Vistas de lista, formulario y búsqueda. Filtros por estado y «Mis solicitudes»; agrupar por proveedor, estado o solicitante.
- Menú «Solicitudes de pago».

## Qué hace (tramo B)

- **Niveles de aprobación** (`payment.approval.level`): cada nivel tiene un monto mínimo y un aprobador. Los configura el administrador en **Solicitudes de pago → Configuración → Niveles de aprobación**. Ejemplo: «Jefe de área» desde 0 y «Gerencia» desde 1.000.
- **Al enviar**, el sistema elige el nivel con el mayor monto mínimo que no supere el monto de la solicitud. El monto se compara en la moneda de la compañía (si la solicitud está en otra moneda, se convierte con la tasa de la fecha de la solicitud). El aprobador del nivel queda asignado a la solicitud y recibe una actividad «Por hacer» para revisarla. Si los niveles cambian después, el aprobador ya asignado no cambia.
- **Solo el aprobador asignado** aprueba o rechaza. Otro usuario con el grupo Aprobador recibe un error. Al aprobar queda registrado quién y cuándo, y la actividad se cierra.
- **Rechazo con motivo:** el botón «Rechazar» abre un asistente con el motivo obligatorio. El motivo queda en el campo de la solicitud y en un mensaje del chatter dirigido al solicitante, que recibe el aviso.
- **Pago:** el botón «Marcar como pagada» abre un asistente donde Tesorería elige el diario (banco o caja) y la fecha. Crea un `account.payment` de proveedor, saliente, por el monto y la moneda de la solicitud, lo publica y deja la solicitud como pagada. El pago queda vinculado: la solicitud muestra el número y la fecha del pago a cualquiera que la pueda ver, y quien tiene permisos de Contabilidad (Facturación o solo lectura) tiene además el botón «Pago» para abrirlo. El pago guarda la solicitud en el campo `payment_request_id` (no se muestra en el formulario del pago). No se puede pagar dos veces.
- **Reporte PDF** (QWeb), botón «Imprimir» en solicitudes aprobadas o pagadas: número, fecha, proveedor, concepto, monto y moneda, solicitante, quién aprobó y cuándo, y el pago si ya se hizo.

### Casos límite que el envío rechaza con un mensaje claro

| Caso | Qué pasa |
|---|---|
| Ningún nivel cubre el monto (no hay niveles, o el primero empieza por encima del monto) | El envío falla: «No hay un nivel de aprobación para este monto. Pide a un administrador que configure los niveles de aprobación.» La solicitud sigue en borrador. |
| El aprobador del nivel es quien pidió el pago | El envío falla diciendo quién debe aprobar y que un administrador revise los niveles. No se reasigna a otra persona en silencio. |

### Cómo se aplica cada regla (tramo B)

- El aprobador, la fecha de aprobación, el motivo del rechazo y el pago son campos del sistema: ningún usuario los escribe, ni por la interfaz ni llamando al ORM. Solo los escribe el propio módulo, con `sudo()` acotado a ese campo y con un comentario que lo explica.
- El cambio de estado se valida en `write`, igual que en el tramo A: `write({"state": "rejected"})` sin motivo, o `write({"state": "paid"})` sin pago, también fallan. Y `write({"state": "submitted"})` también asigna el aprobador, así que ninguna ruta deja una solicitud enviada sin aprobador.
- El pago usa `sudo()` solo para crear y publicar ese `account.payment`: Tesorería no tiene permisos de Contabilidad y no se los damos. Todo ocurre en la misma transacción; si publicar el pago falla, la solicitud sigue aprobada.
- Tesorería recibe solo permiso de lectura sobre los diarios contables (`account.journal`), para poder elegir el diario en el asistente de pago.
- El número y la fecha del pago se leen con campos relacionados, que Odoo calcula como superusuario. Así el formulario y el PDF los muestran a quien no tiene permisos de Contabilidad, sin darle acceso al pago.
- Los niveles los lee cualquier solicitante (el envío los consulta) y solo los cambia el administrador del sistema.

## Qué se reusa de Odoo

- `mail.thread`: el chatter registra cada cambio de estado, proveedor, monto o moneda, con su autor y su fecha.
- `ir.sequence` con subsecuencias por año para el número.
- `res.groups` y reglas de registro (`ir.rule`) para lo que ve cada grupo.
- `res.partner` para el proveedor y `res.currency` para la moneda y su conversión a la de la compañía.
- `mail.activity.mixin` para la actividad del aprobador.
- `account.payment` y `account.journal` para el pago y el diario.
- `ir.actions.report` con QWeb para el PDF, con el diseño de documento de la compañía.

## Cómo se aplica cada regla

- Ver solo lo suyo: la regla `payment_request_rule_own` (`requester_id = usuario`). Aprobador y Tesorería tienen además una regla de lectura de todas y otra de escritura solo sobre las que no están en borrador.
- Cambios de estado: `write` valida cualquier cambio de estado en `_check_state_change`: grupo, estado de origen y quién es el solicitante. Así falla igual si se pulsa el botón, si se llama al método o si se escribe `state` directamente.
- Una solicitud enviada no se edita: `write` rechaza cambios en los campos de la solicitud fuera de borrador. Vale para todos, también con `sudo()`. El formulario además los muestra de solo lectura.
- Monto mayor que cero: `@api.constrains` con `compare_amounts` de la moneda, así que 0,001 USD cuenta como cero.
- Crear: siempre en borrador, con el número de la secuencia y el usuario actual como solicitante. La regla de registro impide crear a nombre de otro. Al duplicar una solicitud, la copia queda a nombre de quien la duplica.
- Número y solicitante: se fijan al crear y `write` rechaza cambiarlos. Si el solicitante se pudiera cambiar, un aprobador podría pasar su solicitud a otra persona al enviarla y después aprobarla él mismo.
- Borrar: solo en borrador.

## Cómo probarlo

```bash
./odoo test -i prueba-tecnica -d <base_nueva> -m payment_request
```

El comando termina con código 0 aunque haya pruebas con error: hay que leer la línea `... of N tests` del final.

Pruebas en `tests/test_payment_request.py`:

| Criterio | Prueba |
|---|---|
| El solicitante solo ve sus solicitudes | `test_requester_sees_only_own` |
| El solicitante no aprueba, ni por el botón ni por el método | `test_requester_cannot_approve_reject_or_pay`, `test_buttons_by_group_and_state` |
| Un aprobador no aprueba su propia solicitud | `test_approver_cannot_approve_own_request`, `test_number_and_requester_fixed_after_create` |
| Una solicitud enviada no se edita | `test_submitted_request_not_editable` |
| Monto cero o negativo rechazado | `test_amount_must_be_positive` |
| Botones según estado y grupo | `test_buttons_by_group_and_state` |
| Flujo completo y rechazo | `test_full_flow`, `test_rejected_is_final`, `test_state_changes_logged_in_chatter` |
| Orden de estados y doble ejecución | `test_wrong_order_and_double_execution`, `test_no_way_back_to_draft` |
| Otros límites | `test_only_owner_submits`, `test_treasury_cannot_approve_and_approver_cannot_pay`, `test_cannot_create_in_other_state`, `test_cannot_create_for_another_user`, `test_copy_belongs_to_current_user`, `test_unlink_only_draft`, `test_internal_user_is_requester`, `test_create_defaults_and_sequence` |

A mano: con un usuario por grupo (Solicitante, Aprobador, Tesorería), crear una solicitud con el solicitante, enviarla, aprobarla con el aprobador y marcarla como pagada con Tesorería. En cada paso solo debe aparecer el botón de ese grupo.

### Pruebas del tramo B

`tests/test_payment_approval.py`:

| Criterio | Prueba |
|---|---|
| Nivel según el monto, en los bordes | `test_level_is_chosen_by_amount`, `test_level_compares_in_company_currency` |
| Sin nivel para el monto: no se envía | `test_no_level_for_amount_blocks_submit` |
| Aprobador del nivel es el solicitante: no se envía | `test_submit_fails_if_approver_is_requester` |
| Reglas y permisos de los niveles | `test_level_constraints`, `test_level_access`, `test_assigned_approver_does_not_change_with_levels` |
| Actividad para el aprobador | `test_submit_creates_activity_for_approver` |
| Solo el aprobador asignado aprueba | `test_only_assigned_approver_approves`, `test_approval_records_who_and_when` |
| Los campos del sistema no se escriben a mano | `test_system_fields_cannot_be_written_by_users` |
| Rechazo con motivo y chatter | `test_reject_opens_wizard_only_for_assigned_approver`, `test_reject_requires_reason`, `test_reject_stores_reason_and_notifies_in_chatter`, `test_wizard_reject_by_unassigned_approver_fails`, `test_reject_state_needs_reason` |
| Pago vinculado, sin pago doble y todo o nada | `test_pay_creates_vendor_payment_linked_to_request`, `test_treasury_pays_without_accounting_groups`, `test_cannot_pay_twice`, `test_can_only_pay_approved`, `test_paid_state_needs_payment`, `test_pay_is_all_or_nothing`, `test_view_payment_action`, `test_buttons_by_group_and_state` (botón «Pago» solo con Contabilidad) |
| Asistentes por grupo | `test_wizards_are_limited_to_their_group` |
| Reporte con aprobador y fecha, también impreso por el solicitante | `test_report_shows_approver_and_date`, `test_requester_prints_paid_request` |
| Vistas | `test_levels_and_wizard_views_exist` |

Las pruebas del tramo A se ajustaron: ahora crean un nivel general antes de enviar, y rechazan y pagan por los asistentes.

A mano, con un usuario por grupo y un administrador:

1. Como administrador, crear dos niveles: «Jefe de área» desde 0 (con un usuario Aprobador) y «Gerencia» desde 1.000 (con otro).
2. Como solicitante, crear y enviar una solicitud de 150: queda asignada al jefe de área, que ve una actividad.
3. Enviar otra de 5.000: queda asignada a Gerencia.
4. Con el jefe de área, rechazar la primera con un motivo; con el solicitante, ver el motivo en el chatter.
5. Aprobar la de Gerencia con su aprobador, y con Tesorería pagarla eligiendo un diario; abrir el pago desde el botón «Pago» e imprimir la solicitud.

## Cómo se verificó (tramo A)

- Pruebas en una base nueva: `0 failed, 0 error(s) of 20 tests` (antes de agregar el tramo B).
- Antes de escribir el código, las pruebas fallaban porque el módulo no definía los grupos.
- Se quitaron a propósito el bloqueo de edición, los dos chequeos de grupo y el de auto-aprobación. Fallaron las 4 pruebas que los cubren, y después se restauró el código.
- Instalación en una base nueva: el registro no tiene `WARNING`, `ERROR` ni mensajes de docutils de este módulo. Quedan dos mensajes de docutils (`<string>:38: (ERROR/3)` y `<string>:43: (WARNING/2)`) que salen al cargar el módulo `mail` de Odoo.
- Linter del repositorio (`.pylintrc` y `.pylintrc-mandatory`): solo marca que el autor del manifest no es la OCA, igual que en los otros módulos del repositorio.

## Cómo se verificó (tramo B)

- Pruebas en una base nueva de Odoo 18.0, sin datos demo y con `account` instalado: 47 pruebas del módulo (tramos A y B), sin fallos ni errores. Cubren los niveles por monto, el aprobador asignado con su actividad, que solo él apruebe, el rechazo con motivo en el chatter, el pago vinculado, que no se pueda pagar dos veces y el PDF con quién aprobó y cuándo.
- La primera corrida dio 37 errores con una sola causa: los usuarios de las pruebas no tenían correo, y Odoo no puede notificar la actividad del aprobador sin el correo de quien envía. Se corrigió dándoles un correo de ejemplo en las pruebas.
- Limitación: para enviar una solicitud, el usuario necesita un correo configurado, porque Odoo lo exige al notificar la actividad del aprobador.
- Pruebas en el navegador automatizadas por la IA, con un usuario por grupo: envío con aprobador asignado y su actividad, rechazo con motivo en el chatter, pago con diario y PDF con quién aprobó y cuándo. Después las revisé en el navegador para confirmar.

## Supuestos (tramo A)

- Aprobador y Tesorería incluyen Solicitante, pero no se incluyen entre sí: quien paga no aprueba.
- Todo usuario interno es Solicitante, porque el correo dice que «cualquier empleado» puede pedir un pago.
- El solicitante ve y trabaja solo con sus solicitudes. Aprobador y Tesorería ven todas.
- Un aprobador no puede aprobar su propia solicitud. Sí puede rechazarla.
- Solo se rechaza desde enviada, y solo lo hace un aprobador. Rechazada es un estado final: no hay anular ni volver a borrador (preguntas 5 y 6).
- «Marcar como pagada» la usa solo Tesorería, desde aprobada, y en este tramo solo cambia el estado.
- Solo quien pidió el pago envía la solicitud.
- Nadie puede cambiar una solicitud enviada, tampoco el administrador.
- Solo se borran solicitudes en borrador.
- El solicitante es el usuario que crea la solicitud. Nadie crea solicitudes a nombre de otro.
- La fecha es la de la solicitud, hoy por defecto.
- El proveedor puede ser cualquier contacto. Para limitarlo a proveedores hay que depender de `account`; por ahora el módulo depende solo de `mail`.
- La moneda por defecto es la de la compañía; se puede elegir cualquier moneda activa.
- El concepto es un texto corto y obligatorio.
- El número se asigna al crear la solicitud, con 4 dígitos, y vuelve a 0001 cada año. El año es el de la creación.
- El monto no se suma al agrupar, porque las solicitudes pueden estar en monedas distintas.
- El administrador no recibe Aprobador ni Tesorería al instalar, para que nadie apruebe y pague por defecto. Los grupos se asignan en Ajustes. El administrador ve el menú porque es usuario interno.

## Supuestos (tramo B)

- **Un solo aprobador por solicitud**, el del nivel que corresponde al monto. Los pagos grandes los aprueba solo gerencia, sin pasar antes por el jefe (preguntas 1, 2 y 8).
- **El aprobador sale del nivel, no del jefe del empleado.** No se usa la app Empleados.
- **El monto se compara en la moneda de la compañía** que envía, con la tasa de la fecha de la solicitud. Los niveles son por compañía; la regla de registro multi-compañía queda para el tramo C.
- **Sin nivel que cubra el monto, no se envía.** Es mejor un error claro que una solicitud enviada que nadie aprueba, que es justo el problema que Carolina describe. Para que casi no pase, conviene un nivel con monto mínimo 0.
- **Si el aprobador del nivel es quien pidió el pago, no se envía** y no se reasigna a otra persona en silencio. El mensaje pide a un administrador revisar los niveles.
- **Solo el aprobador asignado rechaza o aprueba**, aunque haya otros aprobadores.
- **El rechazo lleva motivo obligatorio** y sigue siendo un estado final.
- **El pago es suelto al proveedor, por el monto total y en la moneda de la solicitud**, sin cruzarlo con una factura ni pagos parciales (pregunta 7). Se publica al crearlo.
- **El diario lo elige Tesorería** entre los diarios de banco y caja de la compañía. El módulo no asume uno.
- **Tesorería no necesita permisos de Contabilidad:** el pago se crea y se publica con `sudo()` acotado a ese pago.
- **El reporte no lleva firmas**: muestra quién aprobó y cuándo (pregunta 3).
- **El módulo ahora depende de `account`** (para el pago y el diario).

## Supuestos y preguntas al cliente

| Pregunta | Supuesto mientras no responde | Tramo que afecta |
|---|---|---|
| 1. ¿Qué rangos califican como pago normal y como pago grande? ¿En qué moneda se mide el monto? ¿Es un solo límite o hay varios niveles? | Niveles configurables por monto mínimo, cada uno con su aprobador. El monto se compara en la moneda de la compañía. | B (y C por la conversión de moneda) |
| 2. ¿Cómo se sabe quién es el jefe de cada empleado? ¿Usan la app Empleados de Odoo con el jefe asignado? | No se usa la app Empleados. El aprobador sale del nivel que corresponde al monto, no del jefe del empleado. | B |
| 3. ¿Qué debe mostrar el documento de la solicitud para la carpeta del proveedor? ¿Lleva firmas? | Número, fecha, proveedor, concepto, monto y moneda, solicitante, quién aprobó y cuándo. Sin firmas: la aprobación queda registrada en Odoo. | B |
| 4. ¿Qué tasa usan para pasar de dólares a bolívares (por ejemplo, la del BCV)? ¿La cargan ustedes a mano cada día o la debe tomar el sistema? | La tasa se carga en Odoo, en las tasas de la moneda, y el sistema usa la de la fecha del pago. No se conecta con el BCV. | C |
| 5. Si el empleado se equivoca después de enviar, ¿puede anularla o alguien se la devuelve a borrador? | Nadie la anula ni la devuelve a borrador. Si hay un error, el aprobador la rechaza. | A |
| 6. Si se rechaza, ¿la puede corregir y reenviar, o crea una nueva? | Rechazada es un estado final. El empleado crea una solicitud nueva. | A |
| 7. El pago que registra tesorería, ¿se cruza con la factura del proveedor o es un pago suelto? ¿Puede haber pagos parciales? | Pago suelto al proveedor por el monto total, sin cruzarlo con la factura. Sin pagos parciales. | B |
| 8. Los pagos grandes, ¿los aprueba solo gerencia o primero el jefe y después gerencia? | Un solo aprobador por solicitud: el del nivel que corresponde al monto. Los pagos grandes los aprueba solo gerencia. | B |
| 9. ¿Todos los empleados que van a pedir pagos tienen usuario en Odoo? | Sí. Todo usuario interno queda como Solicitante. | A |
| 10. Si ningún nivel cubre el monto de una solicitud, ¿qué debe pasar? Por ejemplo, si el pago más pequeño que cubre su política empieza por encima de cero. | No se puede enviar: sale un error que pide configurar los niveles. Se recomienda un nivel desde 0. | B |

## Limitaciones conocidas

- Lo que el correo pide y todavía no está: pago en bolívares de una solicitud en dólares con la tasa de la fecha del pago, multi-compañía con reglas de registro, y que dos aprobadores actuando a la vez no se pisen (tramo C).
- El aprobador de un nivel puede dejar de serlo (por ejemplo, se va de la empresa): las solicitudes ya asignadas a él quedan esperándolo. No hay reasignación; hoy habría que rechazar y volver a crear la solicitud.
- El pago se crea siempre en la moneda de la solicitud; si el diario no admite esa moneda, Odoo lo avisa al publicar y la solicitud sigue aprobada.
- El reporte no permite imprimir borradores ni enviadas: el botón solo aparece en solicitudes aprobadas o pagadas.
- Tesorería registra el pago pero, sin permisos de Contabilidad, no puede abrirlo: ve su número y su fecha en la solicitud. Para abrirlo hace falta Facturación o Contabilidad de solo lectura.
- Un aprobador ve los borradores de otros, pero no puede editarlos ni enviarlos.
- Un aprobador o Tesorería puede borrar sus propios borradores, como cualquier solicitante, pero no los de otros.
- Odoo no impide asignar Aprobador y Tesorería a la misma persona. Esa separación depende de quien administra los usuarios.
- Los textos están en español en el código. El módulo no trae traducciones.