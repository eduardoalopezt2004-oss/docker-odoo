# Plan de migración: tipo de vehículo como catálogo

`fleet_inspection` de **18.0.1.0.0** a **18.0.1.1.0** en la base de producción de un cliente.

Está escrito para quien ejecute la actualización. No hace falta conocer el código: cada paso dice qué comando correr, qué resultado esperar y qué hacer si no sale así. Ante cualquier resultado distinto del esperado, **no se sigue al paso siguiente**: se va a [Reversión](#reversión).

## Resumen

| | |
|---|---|
| Qué cambia | El tipo de vehículo de cada inspección deja de ser una lista fija (`motorcycle`, `car`, `truck`, `other`) y pasa a ser un registro del catálogo `fleet.inspection.vehicle.type` (Moto, Carro, Camión, Otro) |
| Qué hace la migración | 1) Antes de cambiar la tabla, guarda el valor viejo en la columna `vehicle_type_legacy`. 2) Carga el catálogo. 3) Asigna a cada inspección su tipo por lotes de 1.000, solo a las que no tienen tipo. 4) Verifica que ninguna quede sin tipo |
| Si algo no cuadra | La migración se detiene con un mensaje, Odoo deshace la actualización completa y la base queda como estaba |
| Se puede repetir | Sí. Una segunda ejecución no cambia nada: solo completa tipos vacíos y no toca la columna ya renombrada (comprobado en el ensayo) |
| Datos que no se tocan | Todo lo demás de la inspección. El valor viejo queda guardado en `vehicle_type_legacy` |
| Duración esperada | Ver [Tiempos del ensayo](#tiempos-del-ensayo). Reservar al menos el triple del tiempo medido, más el respaldo |
| Usuarios | No deben usar Odoo desde el paso 1 hasta terminar el paso 4 |

Comandos: se corren desde la raíz del repositorio `docker-odoo`, con la instancia `prueba-tecnica` levantada (`./odoo start prueba-tecnica`). Si la instancia del cliente tiene otro nombre, se cambia en todos los comandos. Al final está el [equivalente sin el CLI](#equivalente-sin-el-cli-del-repositorio).

Variables que usan los comandos (se definen una vez en la terminal):

```bash
BASE=<nombre_de_la_base_del_cliente>
SVC="docker compose -f docker-compose.generated.yml exec -T odoo-prueba-tecnica"
CHECK=src/custom/prueba-tecnica/fleet_inspection/scripts/check_vehicle_types.py
mkdir -p ~/migracion_fleet
```

## Antes del día

- [ ] **Ensayo en una copia de la base de producción.** Se restaura el último respaldo con otro nombre y se hacen ahí los pasos 1 a 4, midiendo los tiempos. Si el ensayo falla o tarda más de lo que permite la ventana, no se migra producción. Los datos de prueba del ensayo con 10.000 inspecciones y sus tiempos están en el README, sección *Ensayo con 10.000 inspecciones*.
- [ ] El código a desplegar está integrado y tiene un commit o etiqueta concreto (anotarlo: `<ref_nueva>`). Anotar también el commit que corre hoy en producción (`<ref_anterior>`): `git rev-parse HEAD`.
- [ ] Hay espacio en disco para el respaldo (al menos el tamaño de la base más el filestore).
- [ ] Ventana acordada con el cliente y usuarios avisados de que Odoo no estará disponible.
- [ ] En producción el servidor no debe tener recarga automática de código (`dev_mode` con `reload`). Si la tiene, al cambiar el código el servidor arrancaría con la versión nueva sobre la base vieja.

## Paso 1. Respaldo

1. Confirmar que nadie está usando Odoo.
2. Respaldar base y filestore:

   ```bash
   scripts/odoo_backup backup prueba-tecnica -d $BASE -p ~/migracion_fleet/
   ls -lh ~/migracion_fleet/
   ```

   **Esperado:** un archivo `.zip` con tamaño razonable (no de pocos KB). Anotar su nombre: `<respaldo.zip>`.

3. **Verificar que el respaldo se puede restaurar**, en una base aparte:

   ```bash
   ./odoo restore prueba-tecnica -z ~/migracion_fleet/<respaldo.zip> -d ${BASE}_verif
   $SVC odoo shell -d ${BASE}_verif --no-http < $CHECK | tee ~/migracion_fleet/0_respaldo.txt
   ```

   **Esperado:** mismo total y mismos conteos que el paso 2 en la base real. Después se borra la copia: `./odoo psql remove prueba-tecnica -d ${BASE}_verif`.

## Paso 2. Verificación previa

```bash
$SVC odoo shell -d $BASE --no-http < $CHECK | tee ~/migracion_fleet/1_antes.txt
```

**Esperado:**

- `Versión instalada de fleet_inspection: 18.0.1.0.0`
- `Formato: 18.0.1.0.0 (selección)`
- En *Por tipo* solo aparecen `motorcycle`, `car`, `truck` y `other`.

**Si aparece otro valor** (por ejemplo `van`) o un tipo vacío: no seguir. La migración se detendría igual, pero hay que decidir con el cliente a qué tipo del catálogo va ese valor antes de migrar.

Guardar `1_antes.txt`: es la referencia para el paso 4.

## Paso 3. Ejecución

1. Poner el código nuevo:

   ```bash
   git fetch origin
   git checkout <ref_nueva>
   grep '"version"' src/custom/prueba-tecnica/fleet_inspection/__manifest__.py
   ```

   **Esperado:** `"version": "18.0.1.1.0"`.

2. Actualizar el módulo, midiendo el tiempo:

   ```bash
   time ./odoo update prueba-tecnica -d $BASE -m fleet_inspection 2>&1 | tee ~/migracion_fleet/2_actualizacion.log
   grep -E "Tipo de vehículo migrado|No se puede migrar|ERROR|CRITICAL" ~/migracion_fleet/2_actualizacion.log
   ```

   **Esperado:** una sola línea con esta forma (los valores entre `< >` dependen de la base):

   ```
   Tipo de vehículo migrado: <N> inspecciones recibieron su tipo del catálogo, en <L> lotes de hasta 1000,
   en <S> s; memoria máxima del proceso: <M> MB. Valor viejo -> tipo: car -> Carro: <n>, ...
   ```

   El número de inspecciones debe ser el total de `1_antes.txt`. No debe aparecer `ERROR`, `CRITICAL` ni `No se puede migrar`.

   **Si aparece `No se puede migrar` o un error:** Odoo deshizo la actualización. Ir a [Reversión A](#a-la-actualización-falló-paso-3).

3. Reiniciar el servidor para que cargue el código nuevo:

   ```bash
   ./odoo restart prueba-tecnica
   ```

## Paso 4. Verificación posterior

```bash
$SVC odoo shell -d $BASE --no-http < $CHECK | tee ~/migracion_fleet/3_despues.txt
```

**Esperado:**

- `Versión instalada de fleet_inspection: 18.0.1.1.0`
- `Formato: 18.0.1.1.0 (catálogo)`
- El mismo total que en `1_antes.txt`.
- Cada valor viejo con el mismo conteo que en `1_antes.txt` y su tipo correcto: `car -> Carro`, `motorcycle -> Moto`, `other -> Otro`, `truck -> Camión`.
- `Inspecciones sin tipo (debe ser 0): 0`

En el navegador, con un usuario supervisor:

- **Flota → Configuración → Tipos de vehículo** muestra Moto, Carro, Camión y Otro.
- Abrir tres inspecciones antiguas en estados distintos (borrador, aprobada, rechazada) y comprobar que el tipo es el mismo que tenían.
- Crear una inspección nueva en borrador y elegir un tipo del catálogo; después borrarla.

Si todo coincide: avisar al cliente de que Odoo está disponible y guardar la carpeta `~/migracion_fleet/` con el respaldo y los registros. Si algo no coincide: [Reversión B](#b-se-encontró-un-problema-después-de-actualizar).

## Reversión

### A. La actualización falló (paso 3)

Odoo hace la actualización en una sola transacción: si falla, no queda nada a medias.

1. Confirmar que la base quedó como antes:

   ```bash
   $SVC odoo shell -d $BASE --no-http < $CHECK
   ```

   **Esperado:** igual que `1_antes.txt` (versión `18.0.1.0.0`, formato selección, mismos conteos).

2. Volver al código anterior y reiniciar:

   ```bash
   git checkout <ref_anterior>
   ./odoo restart prueba-tecnica
   ```

3. Mandar `2_actualizacion.log` a desarrollo. Si el mensaje es `No se puede migrar`, dice qué valores o cuántas inspecciones lo impidieron.

Si el paso 1 de esta sección no da lo esperado, seguir con la reversión B.

### B. Se encontró un problema después de actualizar

Se restaura el respaldo del paso 1. **Todo lo que se haya registrado en Odoo después del respaldo se pierde**: si los usuarios ya trabajaron, decidir con el cliente antes de restaurar.

```bash
git checkout <ref_anterior>
./odoo psql remove prueba-tecnica -d $BASE
./odoo restore prueba-tecnica -z ~/migracion_fleet/<respaldo.zip> -d $BASE
./odoo restart prueba-tecnica
$SVC odoo shell -d $BASE --no-http < $CHECK
```

**Esperado:** igual que `1_antes.txt`.

No se ofrece deshacer la migración en la misma base, cambiando la columna de vuelta a texto. Sería posible porque el valor viejo queda en `vehicle_type_legacy`, pero ese camino no está probado y restaurar el respaldo sí.

## Tiempos del ensayo

Medidos con 10.000 inspecciones en la base de ensayo. El detalle y los comandos están en el README.

| Paso | Tiempo |
|---|---|
| Respaldo (`odoo_backup`) | pendiente de medir |
| Actualización completa (`./odoo update`, paso 3.2) | pendiente de medir |
| Migración del tipo dentro de la actualización (línea `Tipo de vehículo migrado`) | pendiente de medir |
| Memoria máxima del proceso de actualización | pendiente de medir |
| Segunda actualización (idempotencia) | pendiente de medir |
| Restauración (`./odoo restore`) | pendiente de medir |

## Equivalente sin el CLI del repositorio

Para un servidor que no use `./odoo`:

| Paso | Comando |
|---|---|
| Respaldo | `pg_dump -Fc -d $BASE -f antes.dump` y copia de `~/.local/share/Odoo/filestore/$BASE` (o la ruta `data_dir` del servidor) |
| Verificación previa y posterior | `odoo shell -d $BASE --no-http < scripts/check_vehicle_types.py` |
| Actualizar | `odoo -d $BASE -u fleet_inspection --stop-after-init` con el servidor detenido |
| Restaurar | `dropdb $BASE && createdb $BASE && pg_restore -d $BASE antes.dump`, y devolver el filestore |
