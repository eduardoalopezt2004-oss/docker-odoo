# Cambios de `fleet_inspection`

## 18.0.1.1.0

- El tipo de vehículo pasa de una lista fija (moto, carro, camión, otro) a un catálogo, `fleet.inspection.vehicle.type`, que administra el supervisor en Flota → Configuración → Tipos de vehículo.
- El campo conserva su nombre técnico, `vehicle_type`, y ahora es un many2one.
- Al actualizar, `migrations/18.0.1.1.0` asigna a cada inspección existente su tipo del catálogo, incluido «Otro». Detiene la actualización si algún valor no tiene destino.
- El valor anterior queda guardado en la columna `vehicle_type_legacy`.
- La migración asigna los tipos por lotes de 1.000 inspecciones, se puede ejecutar dos veces sin cambiar nada y deja en el registro cuántas inspecciones, cuántos lotes, el tiempo y la memoria máxima.
- `scripts/` trae un generador de inspecciones de prueba para la versión anterior y un conteo de solo lectura para antes y después de migrar. El procedimiento para producción está en `MIGRATION_PLAN.md`.

## 18.0.1.0.0

- Migración de Odoo 16 a Odoo 18 sin cambios de funcionamiento. El detalle está en el README.
