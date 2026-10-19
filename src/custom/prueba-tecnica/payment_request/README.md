# Solicitudes de pago (`payment_request`)

Ejercicio 4 de la prueba técnica. Hoy las solicitudes de pago a proveedores llegan por WhatsApp y nadie sabe cuáles se aprobaron. Con este módulo cualquier empleado pide el pago en Odoo, y el chatter de cada solicitud guarda quién la envió, quién la aprobó y quién la pagó.

## Tramos

- [x] A: modelo, flujo de estados, grupos, vistas y menú.
- [ ] B: no iniciado.
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

## Qué se reusa de Odoo

- `mail.thread`: el chatter registra cada cambio de estado, proveedor, monto o moneda, con su autor y su fecha.
- `ir.sequence` con subsecuencias por año para el número.
- `res.groups` y reglas de registro (`ir.rule`) para lo que ve cada grupo.
- `res.partner` para el proveedor y `res.currency` para la moneda.

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

## Cómo se verificó

- Pruebas en una base nueva: `0 failed, 0 error(s) of 20 tests`.
- Antes de escribir el código, las pruebas fallaban porque el módulo no definía los grupos.
- Se quitaron a propósito el bloqueo de edición, los dos chequeos de grupo y el de auto-aprobación. Fallaron las 4 pruebas que los cubren, y después se restauró el código.
- Instalación en una base nueva: el registro no tiene `WARNING`, `ERROR` ni mensajes de docutils de este módulo. Quedan dos mensajes de docutils (`<string>:38: (ERROR/3)` y `<string>:43: (WARNING/2)`) que salen al cargar el módulo `mail` de Odoo.
- Linter del repositorio (`.pylintrc` y `.pylintrc-mandatory`): solo marca que el autor del manifest no es la OCA, igual que en los otros módulos del repositorio.

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

## Limitaciones conocidas

- Lo que el correo pide y este tramo todavía no hace: niveles de aprobación por monto, motivo del rechazo, registro contable del pago, documento impreso y pago en bolívares de montos en dólares.
- Un aprobador ve los borradores de otros, pero no puede editarlos ni enviarlos.
- Un aprobador o Tesorería puede borrar sus propios borradores, como cualquier solicitante, pero no los de otros.
- Odoo no impide asignar Aprobador y Tesorería a la misma persona. Esa separación depende de quien administra los usuarios.
- Los textos están en español en el código. El módulo no trae traducciones.
