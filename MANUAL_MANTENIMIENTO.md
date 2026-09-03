# Manual de mantenimiento de AstroDoncel Studio

Versión de la aplicación: 0.5.0  
Última actualización: 31 de agosto de 2026

Este documento explica las operaciones habituales del despliegue Docker en el
NAS. No es necesario modificar el código para arrancar, parar, actualizar o
cambiar los límites de almacenamiento.

## 1. Resumen para una intervención rápida

Desde la carpeta del repositorio:

```bash
docker compose ps
docker compose logs --tail 100 api worker web cache-maintenance
curl --fail http://127.0.0.1:8080/ready
```

El estado normal es:

- `db`, `api`, `worker`, `web` y `cache-maintenance`: activos;
- `migrate`: terminado con código 0; que figure como `Exited` es correcto;
- `/ready`: responde con `status: ok` y `database: ok`.

Si el NAS se reinicia, los servicios se levantan automáticamente. El script de
arranque solo vuelve a hacer falta después de un `docker compose down` o para
construir una actualización.

## 2. Archivos que se pueden cambiar sin tocar el programa

La configuración privada está en `.env`. Ese archivo no se sube a GitHub. Los
valores disponibles y sus explicaciones están en `.env.example`.

Los datos persistentes son:

- PostgreSQL: catálogo sincronizado, inventario y trabajos;
- `APP_DATA_SOURCE`: caché FITS descargada y artefactos;
- `ECALLISTO_HOST_DIR`: archivo e-CALLISTO existente, montado como solo lectura.

No se debe editar `docker-compose.yml` para cambiar contraseñas, rutas o límites
ordinarios; para eso está `.env`.

## 3. Arrancar, parar y reiniciar

Arranque o recreación normal:

```bash
sh scripts/docker-up.sh
```

Reiniciar sin borrar datos:

```bash
docker compose restart
```

Parar y volver a arrancar:

```bash
docker compose down
docker compose up -d
```

`docker compose down` conserva los volúmenes. No se debe añadir `-v`, porque
eliminaría los volúmenes persistentes administrados por Docker.

## 4. Actualizar la aplicación

Antes de actualizar, crea una copia:

```bash
sh scripts/backup.sh
```

Después:

```bash
git pull --ff-only
docker compose up --build -d
docker compose ps
curl --fail http://127.0.0.1:8080/ready
```

La migración de base de datos se ejecuta antes de la API. Tras actualizar,
comprueba al menos un espectrograma, Burst Reports, Xmatch y una tarea de
Combine u Overview.

Para conocer la versión desplegada:

```bash
curl http://127.0.0.1:8080/health
```

La respuesta incluye el nombre y la versión. El valor procede del archivo
`VERSION`; no debe cambiarse manualmente en varios sitios.

## 5. Burst Reports desde MySQL/MariaDB

AstroDoncel Studio no escribe en la base del portal original. La lee y mantiene
una copia propia en PostgreSQL para que una interrupción temporal de MySQL no
deje el resto de la aplicación fuera de servicio.

La configuración del NAS debe contener:

```dotenv
BURST_CATALOG_SOURCE=uah_mysql
BURST_SOURCE_MYSQL_HOST=host.docker.internal
BURST_SOURCE_MYSQL_PORT=3306
BURST_SOURCE_MYSQL_DATABASE=srbs_callisto
BURST_SOURCE_MYSQL_USER=<usuario_de_solo_lectura>
BURST_SOURCE_MYSQL_PASSWORD='<contraseña>'
BURST_SOURCE_MYSQL_TABLE=
BURST_SOURCE_REFRESH_MINUTES=60
```

Recomendaciones:

- usar un usuario exclusivo con permiso `SELECT`, nunca la cuenta
  administradora del servidor;
- mantener la contraseña únicamente en `.env`;
- dejar `BURST_SOURCE_MYSQL_TABLE` vacío solo si hay una única tabla o vista
  compatible;
- si la contraseña contiene `$`, conservar las comillas simples mostradas.

Después de cambiar `.env`:

```bash
docker compose up -d --force-recreate api
docker compose logs --tail 100 api
```

Abre Burst Reports para el mes actual y confirma que la interfaz indica
`AstroDoncel UAH database`. Si MySQL rechaza la conexión, lo más probable es que
el servicio escuche solo en `localhost` o que el usuario solo esté autorizado
desde allí. El administrador de MySQL debe habilitar una interfaz alcanzable
desde la red interna de Docker y permitir ese origen manteniendo el permiso
limitado a `SELECT`. MySQL no debe publicarse hacia Internet.

El formato externo se descubre por nombres de columnas. Si aparecen varias
tablas compatibles, el log pedirá fijar `BURST_SOURCE_MYSQL_TABLE`. Si la
estructura cambia, hay que adaptar los alias de `backend/catalog_mysql.py` y
añadir una prueba antes de desplegar.

## 6. Enlaces desde el portal original

El portal puede abrir una observación concreta con:

```text
https://astrodoncel.synology.me/?station=GLASGOW&date=2026-08-25&filename=GLASGOW_20260825_123000.fit.gz
```

También se admiten `estacion`, `fecha` y `archivo`. Siempre deben enviarse los
tres datos. El nombre FITS debe pertenecer a esa estación y fecha. Si el archivo
no está en la caché ni en el archivo local, la aplicación intenta descargarlo de
e-CALLISTO.

## 7. Control del almacenamiento FITS

Los FITS descargados se guardan en `APP_DATA_SOURCE` para no repetir descargas.
No se borran de inmediato después de usarlos. El servicio `cache-maintenance`
aplica una política independiente al archivo e-CALLISTO original.

Configuración inicial propuesta:

```dotenv
FITS_CACHE_MAX_GB=20
FITS_CACHE_MAX_AGE_DAYS=90
FITS_CACHE_MIN_IDLE_MINUTES=60
FITS_CACHE_MIN_FREE_GB=5
FITS_CACHE_PRUNE_INTERVAL_HOURS=6
FITS_CACHE_PRUNE_APPLY=false
```

Los límites significan: intentar que la caché no supere 20 GiB, retirar archivos
de más de 90 días y conservar al menos 5 GiB libres. Ningún FITS descargado o
modificado durante la última hora se borra; la aplicación no registra la fecha
del último acceso de cada usuario.

Primero se deja en simulación:

```bash
docker compose logs --tail 200 cache-maintenance
```

Las líneas `WOULD DELETE` muestran qué borraría. Después de revisar con el
responsable del NAS que 20/90/5 son límites adecuados, cambia:

```dotenv
FITS_CACHE_PRUNE_APPLY=true
```

y recrea únicamente ese servicio:

```bash
docker compose up -d --force-recreate cache-maintenance
docker compose logs -f cache-maintenance
```

Protecciones incorporadas:

- el contenedor de limpieza solo monta `APP_DATA_SOURCE`;
- no monta `ECALLISTO_HOST_DIR` y, por tanto, no puede borrar el archivo original;
- solo considera extensiones FITS en la raíz de la caché;
- ignora enlaces simbólicos y archivos recientes;
- exige la marca `.astrodoncel-cache` creada por la API;
- antes de borrar comprueba que tamaño y fecha no hayan cambiado.

La herramienta manual también simula por defecto:

```bash
docker compose run --rm cache-maintenance python -m tools.prune_cache --data-dir /data
```

No hace falta respaldar la caché descargada para conservar información
científica original: cualquier FITS eliminado puede volver a obtenerse del
archivo local o remoto. Sí conviene respaldar PostgreSQL y los artefactos que se
quieran conservar.

## 8. Proxy inverso y HTTPS

El contenedor web atiende HTTP en el puerto interno publicado, normalmente
8080. HTTPS termina en el proxy inverso de Synology; no se configura dentro del
contenedor.

Regla esperada:

- origen: `HTTPS`, dominio público, puerto `443`;
- destino: `HTTP`, `localhost`, puerto `8080`;
- certificado: el correspondiente al dominio público.

No es necesario habilitar HTTPS ni el puerto 443 dentro del contenedor. Tras
renovar o sustituir un certificado, comprueba el dominio desde un navegador
externo y `/ready` desde el propio NAS.

## 9. Copias de seguridad

Crear una copia completa:

```bash
sh scripts/backup.sh
```

El script guarda `postgres.dump`, `app-data.tar.gz` y sus hashes en una carpeta
fechada dentro de `backups/`. Para copiar solo PostgreSQL:

```bash
sh scripts/backup.sh --database-only
```

Después hay que copiar esa carpeta a otro almacenamiento; una copia que vive
solo en el mismo disco no protege frente a una avería del NAS.

La restauración sobrescribe estado persistente y debe ensayarse primero en una
instalación de prueba. Antes de realizarla en producción, detén `web`, `api` y
`worker`, conserva una copia adicional y verifica los hashes. El procedimiento
exacto dependerá de si `APP_DATA_SOURCE` es un volumen Docker o una ruta del
NAS; no debe improvisarse sobre la instancia activa.

## 10. Diagnóstico rápido

| Problema | Comprobación |
|---|---|
| El portal no abre | `docker compose ps` y `docker compose logs web api` |
| `/ready` devuelve 503 | `docker compose logs db migrate api` |
| Una tarea no avanza | `docker compose logs worker` |
| Burst Reports está vacío | `docker compose logs api`; revisar usuario, host y tabla MySQL |
| No aparece un FITS | revisar fecha/estación y la salida de API al acceder a e-CALLISTO |
| El disco sigue creciendo | comprobar el log y `FITS_CACHE_PRUNE_APPLY` |
| HTTPS falla, pero `localhost:8080` funciona | revisar certificado y regla del proxy Synology |

Para seguir un problema en tiempo real:

```bash
docker compose logs -f --tail 100 api worker cache-maintenance
```

No pegues el contenido completo de `.env` en incidencias o correos. Describe la
variable afectada ocultando contraseñas.

## 11. Mapa mínimo del código

| Elemento | Responsabilidad |
|---|---|
| `frontend/src/App.jsx` | navegación, selección de estación/fecha/FITS y enlace compartible |
| `frontend/src/Spectrogram.jsx` | gráfico y herramientas de análisis visibles |
| `frontend/src/BurstCatalog.jsx` | página Burst Reports |
| `frontend/src/Statistics.jsx` | estadísticas y Xmatch |
| `backend/main.py` | API principal, archivo FITS, procesamiento y arranque |
| `backend/api_features.py` | catálogo, exportaciones, curvas y tareas |
| `backend/catalog.py` | normalización y copia local de catálogos |
| `backend/catalog_mysql.py` | lectura de la base MySQL externa |
| `backend/worker.py` | tareas científicas pesadas |
| `tools/prune_cache.py` | plan y ejecución segura de limpieza FITS |
| `docker-compose.yml` | servicios, volúmenes, red y healthchecks |

Antes de cambiar código se ejecutan las pruebas indicadas en `README.md`. La
carpeta `Sahan/` es material de referencia y no se modifica.
