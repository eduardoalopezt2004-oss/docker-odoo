# Solicitudes de pago (`payment_request`)

Ejercicio 4 de la prueba técnica. Hoy las solicitudes de pago a proveedores llegan por WhatsApp y nadie sabe cuáles se aprobaron. Con este módulo cualquier empleado pide el pago en Odoo, y el chatter de cada solicitud guarda quién la envió, quién la aprobó y quién la pagó.

## Tramos

- [x] A: modelo, flujo de estados, grupos, vistas y menú.
- [x] B: niveles de aprobación por monto, aprobador asignado, rechazo con motivo, pago con `account.payment` y reporte PDF.
- [x] C: pago en otra moneda con la tasa del día del pago, multi-compañía con reglas de registro y numeración por compañía, bloqueo de concurrencia en la base y `ARCHITECTURE.md`.

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

## Qué hace (tramo C)

Las decisiones, con lo que se descartó y por qué, están en [`ARCHITECTURE.md`](ARCHITECTURE.md).

- **Pago en otra moneda.** El pago sale en la moneda del diario que elige Tesorería. Una solicitud en dólares pagada desde un banco en bolívares se convierte con la tasa del día del pago. Antes de confirmar, el asistente muestra el monto en bolívares y la tasa, por ejemplo «1 USD = 40 VES (tasa del 20/10/2026)», con la fecha en el formato del idioma del usuario. La solicitud y el PDF guardan el monto pagado, su moneda y la tasa usada.
- **Sin tasa del día, no se paga.** Si no hay tasa cargada para la fecha del pago, el asistente lo avisa y el pago se bloquea con un mensaje que dice qué tasa cargar y dónde (Facturación → Configuración → Contabilidad → Monedas, un menú de quien administra la contabilidad). No se usa una tasa anterior, que es lo que haría Odoo por defecto. Vale también si la solicitud y el diario usan la misma moneda extranjera: el monto no cambia, pero el asiento en la moneda de la compañía se calcula con esa tasa.
- **Multi-compañía.** Cada solicitud es de una compañía: la activa al crearla, y después no cambia, porque el número lleva el código de esa compañía. Cada compañía tiene sus niveles, y el aprobador de un nivel debe tener acceso a su compañía; si se la quitan después, el envío falla con un mensaje que pide revisar los niveles. Una sucursal paga desde sus bancos o los de su compañía principal, como en Odoo. Un usuario solo ve solicitudes y niveles de las compañías que tiene activas. Quien trabaja con varias compañías puede filtrar y agrupar por compañía.
- **Numeración por compañía.** En la ficha de la compañía (Ajustes → Usuarios y compañías → Compañías) hay un campo «Código para solicitudes de pago». Una compañía con código, por ejemplo DA, numera con su propio contador seguido: DA/SP/2026/0001, DA/SP/2026/0002. Sin código, sigue con el contador general: SP/2026/0001. Cambiar el código solo afecta a las solicitudes nuevas. El número nunca se repite.
- **Dos personas a la vez.** Si dos personas actúan sobre la misma solicitud al mismo tiempo (aprobar y rechazar en dos pestañas, un doble clic en «Registrar pago»), solo una lo logra. La otra recibe al instante «Otra persona está procesando esta solicitud. Recarga la página e intenta de nuevo.» y no se hace nada: no se crean dos pagos.
- **Pago fallido.** Si el pago falla (al publicarlo o por falta de tasa), la solicitud sigue aprobada y no queda ningún pago suelto.

### Cómo se aplica cada regla (tramo C)

- Para cada moneda distinta de la de la compañía se revisa la tasa de `res.currency.rate` con que Odoo 18 va a convertir: la de la compañía principal o, si no hay, la que no tiene compañía, la más reciente hasta la fecha del pago. Tiene que ser de esa fecha. Odoo solo deja cargar tasas en la compañía principal, así que una sucursal usa las de su principal. Con la tasa confirmada, el monto lo convierte `res.currency._convert` y la tasa sale de `res.currency._get_conversion_rate`. Si la solicitud y el diario están en la misma moneda no hay conversión, y la tasa del día solo se exige si esa moneda no es la de la compañía.
- La tasa usada queda en `payment_rate`, un campo del sistema como el aprobador: ningún usuario lo escribe. Se guarda sin redondeo, como las tasas de Odoo, y su texto («1 USD = 40 VES») sale de un solo método, sin notación científica.
- Multi-compañía: reglas de registro globales `[('company_id', 'in', company_ids)]` en solicitudes y niveles. Se suman a las de los grupos, así que «Aprobador y Tesorería ven todas» pasa a ser «todas las de sus compañías activas».
- El diario del pago tiene que poder usarse en la compañía de la solicitud, con el mismo criterio que Odoo aplica a los diarios: los de esa compañía o los de su compañía principal. El asistente solo ofrece esos.
- El número se calcula con la compañía con que se guarda la solicitud, también cuando llega por el contexto.
- Concurrencia: `_lock_for_update` hace `SELECT … FOR NO KEY UPDATE NOWAIT` sobre la solicitud antes de validar cualquier cambio de estado, y en el pago antes de crear el `account.payment`. Lo hace PostgreSQL, no un chequeo en Python. `NO KEY UPDATE` choca con otro cambio de estado, pero no con quien solo crea un registro que apunta a la solicitud, como el asistente de pago. El choque no queda como error en el registro de Odoo: es esperado y se convierte en el aviso.
- El contador de una compañía con código es una secuencia de Odoo (`ir.sequence`) de esa compañía, que se crea con `sudo()` acotado la primera vez, porque quien pide el pago no puede crear secuencias.

### Actualizar una base con datos (18.0.1.1.0 → 18.0.1.2.0)

1. Respaldo de la base.
2. Actualizar con el código nuevo: `./odoo update prueba-tecnica -d <base> -m payment_request`.
3. Las solicitudes existentes quedan en la compañía principal (hasta ahora había una sola) y conservan su número. Ninguna compañía tiene código, así que la numeración sigue igual hasta que el administrador ponga uno.
4. Revisar en **Solicitudes de pago** que se ven todas las solicitudes, y que un usuario de otra compañía, si existe, no las ve.

## Qué se reusa de Odoo

- `mail.thread`: el chatter registra cada cambio de estado, proveedor, monto o moneda, con su autor y su fecha.
- `ir.sequence` con subsecuencias por año para el número.
- `res.groups` y reglas de registro (`ir.rule`) para lo que ve cada grupo.
- `res.partner` para el proveedor y `res.currency` para la moneda y su conversión a la de la compañía.
- `mail.activity.mixin` para la actividad del aprobador.
- `account.payment` y `account.journal` para el pago y el diario.
- `ir.actions.report` con QWeb para el PDF, con el diseño de documento de la compañía.
- Tramo C: las tasas de `res.currency.rate` y la conversión de `res.currency`, las reglas de registro multi-compañía, `company_ids` de cada usuario, las secuencias por compañía de `ir.sequence` y el bloqueo de filas de PostgreSQL.

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

### Pruebas del tramo C

En `tests/` (la preparación común está en `tests/common.py`):

| Criterio | Prueba |
|---|---|
| USD pagada desde un diario en VES con la tasa del día del pago | `test_usd_request_paid_from_ves_journal_at_payment_date_rate`, `test_rate_is_the_one_of_the_payment_date` |
| Sin tasa del día no se paga, aunque haya una anterior | `test_missing_rate_on_payment_date_blocks_payment` |
| Se revisa la misma tasa con que convierte Odoo, también en una sucursal | `test_rate_check_looks_at_the_rate_odoo_converts_with`, `test_branch_pays_with_the_rates_of_its_main_company` |
| Una sucursal paga desde los diarios de su principal, nunca desde los de otra compañía | `test_branch_can_pay_from_the_journals_of_its_main_company` |
| El asistente muestra monto y tasa antes de confirmar, con la fecha en el formato del idioma | `test_wizard_shows_amount_and_rate_before_paying` |
| Tasa chica guardada sin redondeo y sin notación científica | `test_small_rate_is_stored_with_full_precision` |
| Misma moneda de la compañía: sin conversión ni tasa | `test_same_currency_needs_no_rate` |
| Misma moneda extranjera: sin conversión, con la tasa del día | `test_same_foreign_currency_needs_the_rate_of_the_day` |
| Pago fallido: la solicitud sigue aprobada | `test_failed_payment_in_ves_leaves_request_approved` (y `test_pay_is_all_or_nothing` del tramo B) |
| PDF con monto pagado y tasa | `test_report_shows_amount_paid_and_rate` |
| Un usuario de la compañía B no ve nada de la A | `test_user_of_company_b_sees_nothing_of_company_a`, `test_user_with_both_companies_sees_only_the_active_ones` |
| Niveles por compañía; aprobador que perdió acceso a la compañía | `test_level_of_the_request_company_is_used`, `test_level_approver_must_have_access_to_its_company`, `test_submit_fails_if_the_approver_lost_access_to_the_company` |
| La compañía no cambia desde que se crea y el número lleva su código; filtro por compañía | `test_company_is_fixed_from_creation`, `test_number_follows_the_company_the_request_is_created_in`, `test_company_cannot_change_after_submit`, `test_search_view_groups_by_company_for_multi_company_users` |
| El aprobador en dos pestañas a la vez: gana una, con los métodos reales | `test_two_tabs_of_the_approver_only_one_wins` |
| Concurrencia con dos conexiones reales a PostgreSQL; el aviso es inmediato y no queda como error en el registro | `test_second_person_gets_an_immediate_notice`, `test_lock_is_free_when_nobody_else_has_it` |
| Crear un registro que apunta a la solicitud no choca con el bloqueo | `test_a_record_pointing_to_the_request_does_not_block_it` |
| El mensaje del correo faltante al rechazar (tramo B) no deja avisos de traducción en el registro | `test_email_message_leaves_no_warning_in_the_log` |
| Todo cambio de estado pasa por el bloqueo antes de hacer nada | `test_every_state_change_takes_the_lock_before_doing_anything` |
| Numeración por compañía con código | `test_company_without_code_keeps_the_general_counter`, `test_each_company_with_code_has_its_own_consecutive_counter`, `test_changing_the_code_only_affects_new_requests`, `test_code_format_and_uniqueness`, `test_requester_without_admin_rights_gets_a_number`, `test_numbers_are_unique_in_the_database` |

Las pruebas de concurrencia confirman datos en la base con conexiones aparte, porque un bloqueo entre dos personas no se puede probar dentro de una sola transacción. Al terminar borran esos datos. Cada conexión tiene un límite de espera de 5 segundos: si alguien quitara `NOWAIT`, la prueba fallaría en lugar de quedarse esperando.

## Cómo se verificó (tramo A)

- Pruebas en una base nueva: `0 failed, 0 error(s) of 20 tests` (antes de agregar el tramo B).
- Antes de escribir el código, las pruebas fallaban porque el módulo no definía los grupos.
- Se quitaron a propósito el bloqueo de edición, los dos chequeos de grupo y el de auto-aprobación. Fallaron las 4 pruebas que los cubren, y después se restauró el código.
- Instalación en una base nueva: el registro no tiene `WARNING`, `ERROR` ni mensajes de docutils de este módulo. Quedan dos mensajes de docutils (`<string>:38: (ERROR/3)` y `<string>:43: (WARNING/2)`) que salen al cargar el módulo `mail` de Odoo.
- Linter del repositorio (`.pylintrc` y `.pylintrc-mandatory`): solo marca que el autor del manifest no es la OCA, igual que en los otros módulos del repositorio.

## Cómo se verificó (tramo B)

- Pruebas en una base nueva de Odoo 18.0, sin datos demo y con `account` instalado: 49 pruebas del módulo (tramos A y B), sin fallos ni errores. Cubren los niveles por monto, el aprobador asignado con su actividad, que solo él apruebe, el rechazo con motivo en el chatter, el pago vinculado, que no se pueda pagar dos veces y el PDF con quién aprobó y cuándo.
- La primera corrida dio 37 errores con una sola causa: los usuarios de las pruebas no tenían correo, y Odoo no puede notificar la actividad del aprobador sin el correo de quien envía. Se corrigió dándoles un correo de ejemplo en las pruebas.
- Supuesto: quien envía o rechaza una solicitud tiene un correo en su usuario, porque Odoo lo usa para avisar al aprobador o al solicitante. Si falta, el módulo lo dice con un mensaje claro antes de intentarlo, en lugar del error técnico de Odoo. Lo fijan las pruebas `test_submit_without_email_has_clear_message` y `test_reject_without_email_has_clear_message`.
- Pruebas en el navegador automatizadas por la IA, con un usuario por grupo: envío con aprobador asignado y su actividad, rechazo con motivo en el chatter, pago con diario y PDF con quién aprobó y cuándo. Después las revisé en el navegador para confirmar.

## Cómo se verificó (tramo C)

- Pruebas en una base nueva de Odoo 18.0, sin datos demo: `0 failed, 0 error(s) of 83 tests` (50 de los tramos A y B y 33 del C). El registro no tiene `bad query` ni avisos de traducción del módulo.
- Antes del código, las pruebas del tramo C fallaban por lo que faltaba: `9 failed, 8 error(s) of 66 tests` (sin `company_id`, `payment_rate`, `_lock_for_update` ni la vista previa del asistente; el pago salía en dólares; el usuario de la compañía B veía la A).
- Las pruebas que se agregaron para corregir un error fallaron primero con el código anterior, por lo que cubren: la sucursal que no podía pagar, la tasa vieja aceptada, la misma moneda extranjera sin tasa, la compañía que se podía cambiar en borrador, los hallazgos de la revisión técnica, la fecha de los avisos, el error del bloqueo en el registro y el aviso de traducción del tramo B. Las que se agregaron para reforzar (el aprobador en dos pestañas, que el aviso sea inmediato) pasaron desde el principio y se comprobaron con las roturas de abajo.
- Se rompieron a propósito cuatro defensas en una sola corrida: sin el bloqueo en `write`, sin `NOWAIT`, aceptando cualquier tasa anterior y sin la regla de compañía en las solicitudes. Fallaron las pruebas que cubren cada una (`8 failed, 1 error(s) of 83 tests`), incluida la de `NOWAIT`, que falló a los 5 segundos en lugar de quedarse esperando. Después se restauró el código.
- Actualización de 18.0.1.1.0 a 18.0.1.2.0 en una base con cinco solicitudes, una en cada estado: `./odoo update prueba-tecnica -d <base> -m payment_request` terminó en 11 s sin errores. Las cinco conservaron número y estado y quedaron en la compañía principal, se crearon la restricción de número único y las dos reglas por compañía, y cada usuario siguió viendo las mismas solicitudes.
- Linter del repositorio (`.pylintrc` y `.pylintrc-mandatory`): solo marca que el autor del manifest no es la OCA, igual que en los otros módulos.
- Lo probé en el navegador con dos compañías y un usuario por grupo: pago en bolívares de una solicitud en dólares con la tasa del día, aviso y bloqueo sin tasa, PDF con el monto pagado y la tasa, usuarios de la compañía B que no ven nada de la A, niveles según las compañías activas y el aprobador en dos pestañas.

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
- **El monto se compara en la moneda de la compañía** de la solicitud, con la tasa de la fecha de la solicitud. Los niveles son por compañía (desde el tramo C, también con reglas de registro).
- **Sin nivel que cubra el monto, no se envía.** Es mejor un error claro que una solicitud enviada que nadie aprueba, que es justo el problema que Carolina describe. Para que casi no pase, conviene un nivel con monto mínimo 0.
- **Si el aprobador del nivel es quien pidió el pago, no se envía** y no se reasigna a otra persona en silencio. El mensaje pide a un administrador revisar los niveles.
- **Solo el aprobador asignado rechaza o aprueba**, aunque haya otros aprobadores.
- **El rechazo lleva motivo obligatorio** y sigue siendo un estado final.
- **El pago es suelto al proveedor, por el monto total**, sin cruzarlo con una factura ni pagos parciales (pregunta 7). Se publica al crearlo. Desde el tramo C sale en la moneda del diario, convertido con la tasa del día del pago.
- **El diario lo elige Tesorería** entre los diarios de banco y caja de la compañía. El módulo no asume uno.
- **Tesorería no necesita permisos de Contabilidad:** el pago se crea y se publica con `sudo()` acotado a ese pago.
- **El reporte no lleva firmas**: muestra quién aprobó y cuándo (pregunta 3).
- **El módulo ahora depende de `account`** (para el pago y el diario).

## Supuestos (tramo C)

- **La contabilidad se lleva en Odoo**, con diarios de banco por moneda (por ejemplo, uno en bolívares y otro en dólares). El pago que crea el módulo es el registro contable. Si la contabilidad se llevara en otro sistema, ese pago lo duplicaría (pregunta 11). Este supuesto ya estaba en el tramo B, al crear un `account.payment`, pero no estaba escrito.
- **La tasa del día se registra en Odoo** (Facturación → Configuración → Contabilidad → Monedas), de la fuente que use el cliente, a mano o con alguna actualización automática. El módulo no obtiene tasas de ninguna fuente externa y no asume cuál es (pregunta 4).
- **El pago usa la tasa exacta del día del pago.** Si falta, el pago se bloquea con un aviso en lugar de usar una tasa anterior.
- **La moneda del pago es la del diario.** Si Tesorería paga en dólares desde un banco en dólares, no hay conversión; si la compañía lleva la contabilidad en bolívares, igual se exige la tasa del día para el asiento.
- **Las solicitudes y los niveles son por compañía**, aunque el correo no dice que el cliente tenga más de una (pregunta 12). Con una sola compañía, nada cambia para el usuario.
- **Numeración:** con código, cada compañía tiene su contador (DA/SP/2026/0001); sin código, sigue el contador general (SP/2026/0001). Una solicitud de pago es un documento interno, no fiscal: no se asume ninguna exigencia legal de numeración (pregunta 12).
- **Si dos personas actúan a la vez**, la segunda recibe un aviso inmediato, sin esperar a que termine la primera, y vuelve a intentar.
- **El PDF muestra lo que se pagó**: el monto en la moneda del pago y la tasa usada (pregunta 3).

## Supuestos y preguntas al cliente

| Pregunta | Supuesto mientras no responde | Tramo que afecta |
|---|---|---|
| 1. ¿Qué rangos califican como pago normal y como pago grande? ¿En qué moneda se mide el monto? ¿Es un solo límite o hay varios niveles? | Niveles configurables por monto mínimo, cada uno con su aprobador. El monto se compara en la moneda de la compañía. | B (y C por la conversión de moneda) |
| 2. ¿Cómo se sabe quién es el jefe de cada empleado? ¿Usan la app Empleados de Odoo con el jefe asignado? | No se usa la app Empleados. El aprobador sale del nivel que corresponde al monto, no del jefe del empleado. | B |
| 3. ¿Qué debe mostrar el documento de la solicitud para la carpeta del proveedor? ¿Lleva firmas? | Número, fecha, proveedor, concepto, monto y moneda, solicitante, quién aprobó y cuándo. Sin firmas: la aprobación queda registrada en Odoo. Desde el tramo C, también el monto pagado en la moneda del pago y la tasa usada. | B y C |
| 4. ¿Qué tasa usan para pasar de dólares a bolívares y de qué fuente sale? ¿Ya la registran en Odoo cada día? Si es así, ¿quién la carga? Si no, ¿quién se encargaría? ¿Les serviría que Odoo la tome sola de esa fuente? | La tasa se registra en Odoo por fecha y el pago usa la del día exacto del pago; si falta, no se paga. El módulo no consulta ninguna fuente. Tomarla automáticamente queda como propuesta en `ARCHITECTURE.md`, a decidir según la fuente. | C |
| 5. Si el empleado se equivoca después de enviar, ¿puede anularla o alguien se la devuelve a borrador? | Nadie la anula ni la devuelve a borrador. Si hay un error, el aprobador la rechaza. | A |
| 6. Si se rechaza, ¿la puede corregir y reenviar, o crea una nueva? | Rechazada es un estado final. El empleado crea una solicitud nueva. | A |
| 7. El pago que registra tesorería, ¿se cruza con la factura del proveedor o es un pago suelto? ¿Puede haber pagos parciales? | Pago suelto al proveedor por el monto total, sin cruzarlo con la factura. Sin pagos parciales. | B |
| 8. Los pagos grandes, ¿los aprueba solo gerencia o primero el jefe y después gerencia? | Un solo aprobador por solicitud: el del nivel que corresponde al monto. Los pagos grandes los aprueba solo gerencia. | B |
| 9. ¿Todos los empleados que van a pedir pagos tienen usuario en Odoo, con su correo configurado? | Sí. Todo usuario interno queda como Solicitante, y quien envía o rechaza necesita un correo para que el aviso llegue a la otra persona. | A |
| 10. Si ningún nivel cubre el monto de una solicitud, ¿qué debe pasar? Por ejemplo, si el pago más pequeño que cubre su política empieza por encima de cero. | No se puede enviar: sale un error que pide configurar los niveles. Se recomienda un nivel desde 0. | B |
| 11. ¿Llevan hoy la contabilidad en Odoo? Si es así, ¿qué diarios de banco tienen y en qué moneda (bolívares, dólares)? | Sí, en Odoo, con diarios de banco por moneda. El pago que registra Tesorería es el registro contable. | B y C |
| 12. ¿Manejan, o piensan manejar, más de una empresa en el mismo Odoo? Si es así, ¿cada empresa necesita su propia numeración de solicitudes? | El módulo separa solicitudes y niveles por compañía. Cada compañía puede tener su propio contador con un código (DA/SP/2026/0001); sin código, comparten el contador general. | C |

## Limitaciones conocidas

- El aprobador de un nivel puede dejar de serlo (por ejemplo, se va de la empresa): las solicitudes ya asignadas a él quedan esperándolo. No hay reasignación; hoy habría que rechazar y volver a crear la solicitud.
- Tramo C: si la primera persona falla (por ejemplo, porque faltaba la tasa), la segunda, que recibió el aviso de «otra persona está procesando», tiene que volver a intentar a mano.
- Tramo C: el contador propio de una compañía se crea con su primera solicitud. Si dos personas de esa compañía crean su primera solicitud en el mismo instante, podrían crearse dos contadores; el número único en la base impide que se repita un número, y una de las dos personas recibiría un error y volvería a intentar.
- Tramo C: un código que otra compañía ya usó (por ejemplo, la compañía X tuvo DA y lo cambió, o está archivada, y la compañía Y toma DA) arranca un contador nuevo en 0001 y chocaría con números que ya existen. El número único en la base impide la repetición, pero esa solicitud no se puede crear. Conviene no reusar un código.
- Tramo C: al actualizar desde 18.0.1.1.0, las solicitudes existentes quedan en la compañía principal. Si el cliente ya usaba varias compañías, habría que revisar a cuál corresponde cada una, y como la compañía ya no se cambia desde la pantalla, corregirla pide un script de datos.
- El reporte no permite imprimir borradores ni enviadas: el botón solo aparece en solicitudes aprobadas o pagadas.
- Tesorería registra el pago pero, sin permisos de Contabilidad, no puede abrirlo: ve su número y su fecha en la solicitud. Para abrirlo hace falta Facturación o Contabilidad de solo lectura.
- Un aprobador ve los borradores de otros, pero no puede editarlos ni enviarlos.
- Un aprobador o Tesorería puede borrar sus propios borradores, como cualquier solicitante, pero no los de otros.
- Odoo no impide asignar Aprobador y Tesorería a la misma persona. Esa separación depende de quien administra los usuarios.
- Los textos están en español en el código. El módulo no trae traducciones.