# Prueba técnica — Desarrollador Odoo

Entrega de Eduardo López. **Versión de Odoo: 18.0.**

Esta carpeta es el directorio de addons de la prueba y tiene los cuatro módulos. Cada uno trae su `README.md` (tramos, cómo probarlo, supuestos y limitaciones) y su `AI_LOG.md`.

## Estado por ejercicio

| Ejercicio | Módulo | Tramo A | Tramo B | Tramo C | Documentos clave |
|---|---|---|---|---|---|
| 1. Integración con API para una tienda en línea | `shop_integration_api` | Hecho | Hecho | No iniciado | README con el contrato, códigos HTTP y ejemplos para la tienda |
| 2. Migración del módulo de inspecciones | `fleet_inspection` | Hecho | Hecho | No iniciado | README con la tabla de cambios de versión, script en `migrations/` |
| 3. Ticket urgente T-200 | `sale_commission` | Hecho | Hecho | Hecho | `INCIDENT.md`, scripts de datos, PR de la rama `hotfix/T-200` |
| 4. Solicitudes de pago con aprobación | `payment_request` | Hecho | Hecho | No iniciado | README con «Supuestos y preguntas al cliente» |

Cada ejercicio se trabajó en su propia rama y se integró con un pull request (merge commit), así que el historial de cada uno se puede seguir commit por commit.

## Levantar el entorno

1. Copia `instances.example.jsonc` a `instances.json` y agrega esta instancia (más una entrada en `odoo_configs` para 18.0 y una en `databases`, como en el ejemplo):

   ```jsonc
   "prueba-tecnica": {
     "odoo_version": "18.0",
     "external_port": 8069,
     "database": "pg16",
     "odoo_config": "18.0_default",
     "overwrite_odoo_config": {
       "addons": ["src/custom/prueba-tecnica"],
       "dev_mode": true
     }
   }
   ```

2. Construye y levanta: `./odoo build` y `./odoo start prueba-tecnica`.

## Correr las pruebas

```bash
./odoo test -i prueba-tecnica -d prueba_limpia \
  -m shop_integration_api,fleet_inspection,sale_commission,payment_request
```

El comando termina con código 0 aunque haya pruebas con error: hay que leer la línea `... of N tests` del final.

Resultado de los cuatro módulos juntos en una base nueva de Odoo 18.0: `0 failed, 0 error(s) of 134 tests`.

## Supuestos del entorno

- El enunciado indica elegir la versión con `ODOO_VERSION` en un `.env`. Este repositorio la configura en `instances.json` (`odoo_version`), así que se siguió al repositorio.
- El comando de pruebas del enunciado no indica la instancia, y el CLI la pide. Se agrega `-i prueba-tecnica`.
- Con varias bases en el mismo servidor y sin `db_filter`, una llamada a la API sin sesión recibe un 404 de Odoo antes de llegar al módulo. Está explicado en el README de `shop_integration_api`.
