# Comisiones de vendedores (`sale_commission`)

Calcula la comisión del vendedor en cada línea de pedido de venta y ofrece un análisis mensual por vendedor.

## Configuración

- **Porcentaje del vendedor:** Ajustes › Usuarios › pestaña *Comisiones* (solo gerentes de ventas).
- **Porcentaje por categoría (desde la 1.1):** Inventario/Ventas › Configuración › Categorías de producto,
  campo *Comisión (%)*. Si la categoría (o una categoría padre) tiene porcentaje, reemplaza al del vendedor.

## Cómo funciona

- Al confirmar el pedido se fija el porcentaje en cada línea y se calcula la comisión sobre el subtotal sin impuestos.
- El botón *Recalcular comisiones* del pedido vuelve a aplicar los porcentajes vigentes.
- Ventas › Reportes › *Comisiones*: tabla dinámica y gráfico por vendedor y mes. Cada vendedor ve solo lo suyo.

## Pruebas

```bash
./odoo test prueba-tecnica sale_commission
```

Si el CLI pide elegir la instancia, la forma sin preguntas es
`./odoo test -i prueba-tecnica -d <base_nueva> -m sale_commission`. El comando termina con código 0 aunque haya
pruebas con error: hay que leer la línea `... of N tests` del final.

## Incidente T-200 (versión 1.1.1)

Los vendedores no podían confirmar pedidos desde la 1.1.0. Todo el detalle está en `INCIDENT.md`.

Tramos completados:

- A: reproducción, causa raíz, corrección y pruebas con vendedor y gerente.
- B: contención, commit que introdujo el error, despliegue y verificación, mensaje al cliente.
- C: script de solo lectura, plan de corrección de datos, búsqueda del mismo patrón y prevención.

`scripts/` tiene dos scripts para correr con `odoo shell`. El módulo no los carga:

- `t200_lineas_afectadas.py`: solo lectura. Lista en un CSV las líneas cuya comisión no es la esperada.
- `t200_corregir_lineas.py`: corrige las líneas de ese CSV ya aprobado. Por defecto solo simula.

El uso y las precondiciones están en la cabecera de cada script y en `INCIDENT.md`.

Supuestos:

- El cliente está en Venezuela (UTC-4): las 12:00 m. del despliegue son las 16:00 UTC.
- El porcentaje esperado de una línea es el de la regla vigente de su categoría o, si no hay, el del vendedor del
  pedido.

Limitaciones conocidas (hallazgos de `INCIDENT.md`, fuera del hotfix):

1. Las líneas sin regla toman el porcentaje de quien confirma, no el del vendedor del pedido: el del gerente si él
   confirma por otro, y 0 % si el cliente acepta o paga la cotización en el portal.
2. *Recalcular comisiones* falla para el vendedor y aplica reglas distintas a las de la confirmación.
3. Cualquier usuario interno puede leer el porcentaje de comisión de los demás.
4. Las columnas de comisión no aparecen en la lista de líneas del pedido.
5. Las líneas agregadas a un pedido ya confirmado quedan sin comisión.
6. Si hay una regla sin compañía y otra de la compañía para la misma categoría, no se prefiere la de la compañía.
