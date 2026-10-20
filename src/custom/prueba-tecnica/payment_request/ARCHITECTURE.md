# Arquitectura del tramo C — `payment_request`

Decisiones del tramo C del ejercicio 4, por qué se tomaron y qué se descartó.

## 1. Pago en otra moneda con la tasa del día del pago

- **Qué hace.** El pago sale en la moneda del diario elegido (por ejemplo, VES). Si es distinta de la de la solicitud (USD), el monto se convierte con `res.currency._get_conversion_rate` a la **fecha del pago**. El asistente muestra el monto y la tasa antes de confirmar, y la solicitud guarda la tasa usada (`payment_rate`). El monto pagado y su moneda se leen del pago.
- **Tasa exacta o nada.** Por defecto, Odoo usa la última tasa anterior a la fecha si no hay una de ese día. Aquí se exige la de ese día exacto, para cada moneda distinta de la de la compañía. Si falta, el pago se bloquea con un mensaje que dice qué tasa cargar y dónde. Pagar con una tasa vieja sin que nadie lo note es peor que detenerse.
- **Descartado:** usar la última tasa disponible y solo mostrar su fecha. Depende de que alguien mire la fecha, y no cumple «la tasa de la fecha del pago».
- **Fuente de la tasa.** El módulo no la obtiene de ningún lado: lee las tasas cargadas en Odoo, a mano o con cualquier actualización automática. No se sabe qué tasa usa el cliente ni de dónde la saca (pregunta 4 del README).
- **Propuesta (no implementada): tasas automáticas.** Con la respuesta del cliente sobre la fuente, se puede agregar un módulo aparte que cargue la tasa del día desde esa fuente, activable y desactivable en Ajustes, que muestre la fecha de cada tasa y deje corregirla a mano. Odoo ya trae ese patrón (`currency_rate_live`, en algunas versiones solo en Enterprise), y algunas localizaciones agregan sus fuentes. Va aparte porque las tasas las usa toda la contabilidad, no solo este módulo. El módulo de pagos no cambiaría: si un día la carga automática falla, el pago se bloquea en lugar de usar una tasa vieja.

## 2. Multi-compañía

- **Qué hace.** La solicitud tiene compañía: la activa del usuario al crearla, que no cambia después de enviarla. Los niveles ya eran por compañía. El nivel se busca entre los de la compañía de la solicitud, y el aprobador de un nivel debe tener acceso a esa compañía.
- **Cómo se aísla.** Con reglas de registro **globales**, `[('company_id', 'in', company_ids)]`, en solicitudes y niveles. Las reglas globales se suman a las de los grupos: un aprobador o Tesorería «ve todas», pero solo las de sus compañías activas. Un usuario de la compañía B no ve nada de la A, ni siquiera abriendo el registro por su id.
- **Descartado:** filtrar por compañía en las búsquedas del código. No protege lo que el código no busca (abrir por id, RPC, informes). La regla de registro sí.
- **Numeración.** Una compañía con código propio («Código para solicitudes de pago», por ejemplo DA) tiene su contador, DA/SP/2026/0001, que se crea con su primera solicitud. Sin código, la compañía sigue con el contador general, SP/2026/0001, así que las bases con una sola compañía no cambian. El número es único en la base.
- **Descartado:** un contador único para todo el grupo, porque cada compañía vería huecos en su numeración. También un contador por compañía sin código, porque el mismo número existiría en varias compañías.

## 3. Concurrencia: solo una persona gana

- **Qué hace.** Antes de cualquier cambio de estado (enviar, aprobar, rechazar, pagar), `_lock_for_update` bloquea la fila con `SELECT … FOR UPDATE NOWAIT` y vuelve a leer la solicitud de la base. En el pago, el bloqueo va **antes** de crear el `account.payment`: un doble clic o dos personas de Tesorería a la vez no crean dos pagos.
- **Quien llega segundo** recibe al instante «Otra persona está procesando esta solicitud…» y no se hace nada. Si la primera ya terminó, PostgreSQL detecta el conflicto (Odoo trabaja en `REPEATABLE READ`), Odoo repite la petición y entonces la segunda ve el estado nuevo.
- **Por qué en la base y no en Python.** Un chequeo en Python («si el estado es aprobada, no sigas») lo hacen las dos personas al mismo tiempo, y las dos lo pasan antes de que cualquiera escriba. Solo un bloqueo en la base serializa a las dos.
- **Descartado:** `FOR UPDATE` sin `NOWAIT`, es decir, que la segunda persona espere y reciba el motivo exacto. Su pantalla queda en espera, y fuera del navegador (scripts, `odoo shell`) no hay reintento automático, así que la persona vería un error técnico. `NOWAIT` se comporta igual en cualquier camino y su prueba es determinista.

## 4. Un pago que falla no deja la solicitud como pagada

Crear el pago, publicarlo y marcar la solicitud como pagada ocurre en una sola transacción. Si algo falla (publicar el asiento o la falta de tasa), Odoo deshace todo: no queda un pago suelto ni una solicitud pagada sin pago. Además, el estado «pagada» exige que exista el pago, también si alguien escribe el estado directamente.

## Verificación al instalar en el cliente

Antes de activar pagos en otra moneda, una consulta de solo lectura sobre `res_currency_rate` (fechas cargadas y huecos por moneda) muestra si el cliente ya registra la tasa de cada día.
