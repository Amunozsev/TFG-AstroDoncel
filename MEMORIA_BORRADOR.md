# AstroDoncel Studio: plataforma web para el análisis de espectrogramas solares e-CALLISTO

Autor: Alfonso Muñoz Sevillano  
Universidad de Alcalá  
Trabajo Fin de Grado, 2026  
Estado: borrador técnico inicial

> Este texto es una base editable. Debe adaptarse a la plantilla oficial de la
> titulación e incorporar las figuras, referencias bibliográficas y resultados
> experimentales definitivos. Los elementos pendientes aparecen marcados como
> **[PENDIENTE]**.

## Resumen

AstroDoncel Studio es una aplicación web para localizar, visualizar, procesar y
comparar espectrogramas solares producidos por la red e-CALLISTO. El proyecto
amplía las capacidades del portal AstroDoncel de la Universidad de Alcalá con
una interfaz interactiva, acceso bajo demanda a observaciones FITS, herramientas
de análisis, cruce con un catálogo de bursts y ejecución controlada de tareas
costosas.

La solución utiliza React y Plotly en la interfaz, FastAPI y bibliotecas
científicas de Python en el servidor, PostgreSQL para la persistencia y un
worker separado para los cálculos largos. Se distribuye mediante contenedores
Docker y dispone de un despliegue en un NAS Synology detrás de un proxy HTTPS.
También se mantiene una demostración temporal en Railway.

La aplicación distingue los valores medidos en los FITS, las inferencias del
modelo de detección y las heurísticas visuales o de disponibilidad. El detector
automático es binario —burst o no burst— y se presenta como ayuda experimental
para priorizar la revisión, no como clasificador del tipo físico ni como sistema
oficial de alertas.

**Palabras clave:** e-CALLISTO, radioastronomía solar, espectrograma, FITS,
FastAPI, React, Docker, visualización científica.

## Abstract

**[PENDIENTE: redactar la versión inglesa cuando el resumen español sea
definitivo.]**

## 1. Introducción

### 1.1 Contexto

Las observaciones radio solares permiten estudiar emisiones que evolucionan en
frecuencia y tiempo. La red e-CALLISTO reúne instrumentos distribuidos en
distintas localizaciones y publica sus observaciones en formato FITS. Esta
distribución aporta cobertura global, pero también produce un volumen y una
heterogeneidad de datos que dificultan la búsqueda y comparación manual.

El portal AstroDoncel de la Universidad de Alcalá ya organiza información sobre
estos eventos y mantiene una base de Burst Reports. AstroDoncel Studio se plantea
como una ampliación: abre la observación seleccionada en el portal, permite
trabajar sobre ella en el navegador y conserva la procedencia de los datos y de
los métodos aplicados.

### 1.2 Problema

El flujo de trabajo original obliga a localizar ficheros, descargarlos y abrirlos
con herramientas independientes. Además, algunos análisis requieren combinar
bloques, comparar estaciones o revisar intervalos largos. Una aplicación web
centralizada puede reducir estos pasos, pero debe resolver varios problemas:

- validar nombres y procedencia de ficheros remotos;
- representar matrices científicas grandes sin bloquear la interfaz;
- separar resultados medidos, inferidos y heurísticos;
- conservar tareas y datos derivados ante reinicios;
- funcionar en un NAS con memoria y almacenamiento limitados;
- mantenerse sin depender del equipo de desarrollo original.

### 1.3 Objetivos

El objetivo general es desarrollar y desplegar una aplicación web mantenible
para explorar y analizar observaciones e-CALLISTO.

Objetivos específicos:

1. descubrir estaciones y ficheros disponibles por fecha;
2. visualizar espectrogramas FITS con controles de procesamiento y contraste;
3. comparar observaciones, medir deriva y obtener curvas de luz;
4. generar resúmenes largos y combinaciones temporales mediante tareas en
   segundo plano;
5. consultar Burst Reports y cruzarlos con la disponibilidad de receptores;
6. permitir enlaces seguros a una observación concreta desde el portal original;
7. desplegar el sistema de forma reproducible con persistencia, comprobaciones
   de estado, copias de seguridad y control de caché;
8. documentar el uso y el mantenimiento para un responsable distinto del autor.

### 1.4 Alcance

La versión entregable analiza radioespectros e-CALLISTO y añade contexto GOES
acotado. Incluye una medición visual de deriva y un detector binario experimental.
No implementa un clasificador de tipos II, III, IV o V ni estimaciones físicas
específicas de bursts tipo II. Esa funcionalidad requeriría definir con expertos
los parámetros, fórmulas, supuestos, incertidumbres y datos de validación. Se
mantiene como trabajo futuro y no como código parcial oculto.

## 2. Antecedentes y tecnologías

### 2.1 e-CALLISTO y formato FITS

**[PENDIENTE: añadir descripción científica respaldada por bibliografía sobre
la red, el tipo de instrumento y el contenido de sus FITS.]**

El sistema usa la cabecera y los ejes de cada FITS como fuente autoritativa para
tiempo, frecuencia, instrumento y coordenadas disponibles. Las coordenadas no
se inventan a partir de una lista manual cuando pueden obtenerse de los datos o
del archivo vivo.

### 2.2 Herramientas de referencia

Parte del diseño científico e interactivo toma como referencia
`e-Callisto_FITS_Analyzer` y `Burst_No_Burst`, de Sahan S. Liyanage. Los métodos
adaptados se integran en una arquitectura web y se acompañan de atribución y
pruebas. La aplicación no incorpora esos proyectos completos ni depende de su
carpeta de referencia para ejecutarse.

### 2.3 Tecnologías elegidas

- **FastAPI:** API HTTP tipada y documentación OpenAPI.
- **Astropy, NumPy, SciPy y SunPy:** lectura FITS y operaciones científicas.
- **ONNX Runtime:** inferencia del detector sin incluir PyTorch en producción.
- **React, Vite y Plotly:** interfaz y gráficos interactivos.
- **SQLAlchemy, Alembic y PostgreSQL:** persistencia y evolución del esquema.
- **Docker Compose y Nginx:** despliegue reproducible y proxy interno.

## 3. Requisitos

### 3.1 Requisitos funcionales

- seleccionar fecha, estación, receptor y fichero;
- cargar datos desde caché, archivo local o archivo público;
- mostrar espectrograma y cabecera FITS;
- aplicar corrección de fondo, mitigación RFI, escalas y contraste;
- comparar capas de hasta seis estaciones;
- medir diferencias de tiempo, frecuencia y deriva en MHz/s;
- trazar y exportar curvas de luz;
- exportar FITS procesado, CSV y manifiesto de análisis;
- ejecutar detección binaria del fichero actual;
- consultar y filtrar Burst Reports;
- representar Xmatch por receptor y abrir el FITS exacto;
- combinar bloques compatibles y crear overview mediante una cola;
- abrir un FITS desde una URL compartible.

### 3.2 Requisitos no funcionales

- impedir el acceso a rutas locales arbitrarias;
- mantener disponible la API si falla una fuente externa opcional;
- conservar datos y tareas entre reinicios;
- limitar CPU, memoria, descargas, logs y caché;
- ejecutar contenedores sin privilegios;
- permitir actualización y diagnóstico mediante comandos documentados;
- verificar el código con pruebas y construcción automatizada.

## 4. Arquitectura y diseño

### 4.1 Vista general

```text
Navegador
   │ HTTPS
   ▼
Proxy inverso Synology
   │ HTTP interno
   ▼
Nginx ──► API FastAPI ──► PostgreSQL
              │                 │
              │                 └── catálogo, inventario y tareas
              ├── archivo e-CALLISTO de solo lectura
              ├── caché FITS descargada
              ├── MySQL UAH de solo lectura
              └── worker persistente
                         │
                         └── artefactos de análisis
```

La interfaz y la API comparten origen en producción. Nginx es el único servicio
publicado por Docker Compose. PostgreSQL, API y worker permanecen en la red
interna.

### 4.2 Resolución de observaciones

Un FITS se busca en el siguiente orden:

1. caché persistente de descargas;
2. archivo e-CALLISTO montado en solo lectura;
3. descarga bajo demanda desde FHNW/ETHZ.

La descarga usa un fichero temporal, limita el tamaño, valida el FITS y lo
publica de forma atómica. Las peticiones externas solo contienen estación,
fecha y nombre; `backend.security` valida los identificadores y resuelve la ruta
dentro de las raíces permitidas.

### 4.3 Persistencia y tareas

PostgreSQL almacena metadatos, meses de catálogo, eventos y trabajos. SQLite
permite desarrollo local sin servicios adicionales. Alembic aplica las
migraciones antes del arranque de la API.

Overview y combinación temporal se ejecutan en un worker persistente. La API
crea el trabajo, el worker lo reclama y actualiza su progreso, y la interfaz
consulta el resultado. Los trabajos se deduplican y pueden recuperarse o
cancelarse de forma cooperativa.

### 4.4 Integración de Burst Reports

La fuente principal del despliegue institucional es la base MySQL/MariaDB del
portal original. La conexión es de solo lectura. El módulo de integración
refleja la tabla o vista, reconoce variantes de nombres de columnas y transforma
cada fila al modelo interno. La copia local se refresca cada hora y elimina de
un mes los eventos que hayan desaparecido de una lectura completada con éxito.

Si la base externa no responde, el error se registra sin mostrar credenciales y
los datos sincronizados anteriormente permanecen en PostgreSQL. Los ficheros
mensuales publicados se mantienen como fuente alternativa para desarrollo o
demostración.

### 4.5 Navegación directa

Una observación se identifica en la URL mediante `station`, `date` y `filename`.
El frontend comprueba su forma y contexto, pero el backend repite la validación.
Así, el portal original puede enlazar AstroDoncel Studio sin exponer una ruta
del NAS ni permitir seleccionar archivos fuera del archivo autorizado.

### 4.6 Gestión del almacenamiento

La caché evita descargar repetidamente el mismo FITS, pero no es una copia
permanente del archivo científico. Un servicio separado calcula una limpieza
por tamaño, antigüedad y espacio libre. Antes de habilitarla produce una
simulación. Solo recibe el volumen de caché; el archivo e-CALLISTO original no
está montado en dicho contenedor.

Además, el plan protege ficheros recientes, ignora enlaces simbólicos, exige una
marca de propiedad de la caché y vuelve a comprobar el fichero antes de borrarlo.

## 5. Implementación

### 5.1 Procesamiento y visualización

El backend lee los ejes temporal y frecuencial del FITS y devuelve matrices con
unidades explícitas. La interfaz representa el espectrograma mediante Plotly.
Los percentiles de contraste se calculan conjuntamente cuando se comparan capas
para mantener una escala visual coherente.

La mitigación RFI y la corrección de fondo son transformaciones instrumentales;
no convierten la intensidad en una magnitud física calibrada. La aplicación
mantiene esta distinción en etiquetas, exportaciones y manifiestos.

### 5.2 Herramientas científicas

- **Drift ruler:** calcula diferencias entre dos puntos elegidos por el usuario.
- **Light curve:** intensidad frente al tiempo en frecuencias seleccionadas,
  alineada con el eje UTC del espectrograma.
- **Combine:** concatena bloques de una estación con ejes compatibles y conserva
  resolución temporal nativa.
- **Spectral overview:** reduce intervalos más largos para localizar actividad,
  mostrando huecos y grupos de receptor.
- **GOES:** contexto opcional dependiente de NOAA/SunPy.

### 5.3 Detección automática

El modelo CNN+MIL devuelve una puntuación binaria para el fichero actual. La
respuesta incluye umbral, versión, hash y método. Una heurística visual separada
puede sugerir una región candidata, pero no se presenta como salida directa de
la red. La ficha completa, métricas aportadas y limitaciones están en
`MODEL_CARD.md`.

### 5.4 Identidad y versionado

La aplicación se denomina **AstroDoncel Studio** para dejar claro que amplía el
portal existente. Un único archivo `VERSION` alimenta la API, la interfaz y la
procedencia del FITS exportado. La versión de este borrador es 0.5.0.

## 6. Pruebas y validación

### 6.1 Pruebas automatizadas

El backend dispone de pruebas de seguridad, FITS, catálogo, exportación,
persistencia, worker, integración MySQL y limpieza de caché. La integración
real del driver se ejecuta en CI contra un servicio MariaDB desechable. El
frontend verifica navegación, enlaces compartibles, paneles, Xmatch y
manifiestos.

La integración continua ejecuta:

- Ruff y pytest;
- migraciones de avance, retroceso y nuevo avance en PostgreSQL;
- ESLint, Vitest y build de producción;
- auditorías de dependencias;
- arranque del stack Compose y de la imagen monolítica.

**[PENDIENTE: incorporar tras la versión final la tabla con número exacto de
pruebas, commit, fecha y resultado de GitHub Actions.]**

### 6.2 Validación visual y funcional

Se han revisado el enlace a un FITS concreto y el hover de los marcadores rojos
de Xmatch. El texto del evento permanece visible al situar el cursor sobre la
línea y el clic conserva estación, receptor y fichero.

**[PENDIENTE: añadir capturas numeradas y protocolo de aceptación con Manuel y
Sahan.]**

### 6.3 Validación científica pendiente

La corrección técnica no implica validación científica. Debe prepararse un
conjunto versionado con eventos y no eventos de varias estaciones y épocas,
reproducir las métricas del detector y validar con expertos la reducción del
overview, la mitigación RFI y cualquier parámetro que se añada en el futuro.

## 7. Despliegue y operación

Docker Compose separa PostgreSQL, migraciones, API, worker, Nginx y mantenimiento
de caché. Los contenedores aplican reinicio automático, logs rotados, usuario
sin privilegios, sistema de archivos de solo lectura cuando es posible y
límites del worker.

El NAS publica AstroDoncel Studio mediante el proxy inverso de Synology. El
certificado HTTPS corresponde al dominio público; los contenedores continúan
atendiendo HTTP solo en la red interna. Esto evita exponer el puerto 8080
directamente a Internet.

El procedimiento de actualización, diagnóstico, MySQL, caché, copias y proxy se
encuentra en `MANUAL_MANTENIMIENTO.md`.

**[PENDIENTE: documentar hardware exacto del NAS, versión DSM/Docker, rutas
reales sin secretos, consumo de memoria/CPU, tiempos y ensayo de restauración.]**

## 8. Seguridad y privacidad

- no se aceptan rutas de archivos proporcionadas libremente por el cliente;
- el archivo científico local se monta como solo lectura;
- la cuenta externa de Burst Reports debe limitarse a `SELECT`;
- `.env`, bases, cachés y backups no se versionan;
- los errores de MySQL no devuelven credenciales al navegador;
- Nginx añade límites básicos y cabeceras de seguridad;
- el portal no incorpora autenticación propia y debe protegerse en el proxy si
  el acceso deja de ser público y de solo lectura.

## 9. Mantenimiento

Las operaciones frecuentes no exigen modificar código: revisar estado, leer
logs, reiniciar, actualizar imágenes, ajustar `.env` y crear backups. El manual
identifica los ficheros responsables de cada área para cambios posteriores.

La caché se mantiene separada de los datos originales. Los límites propuestos
deben validarse con el responsable del NAS en modo simulación antes de activar
el borrado programado.

## 10. Resultados y discusión

El resultado principal es un flujo web integrado que parte de una observación
o de un Burst Report, conserva el contexto de estación/fecha/receptor y permite
analizar y exportar el resultado sin instalar una aplicación de escritorio.
La cola persistente evita mantener cálculos largos dentro de una petición web y
la arquitectura Docker facilita trasladar el sistema entre desarrollo, Railway
y el NAS.

La sincronización de Burst Reports evita depender de los ficheros de texto que
el portal original prevé retirar. Los enlaces directos permiten que ambas webs
coexistan: AstroDoncel sigue siendo el punto de consulta y AstroDoncel Studio
actúa como entorno de análisis.

Las principales limitaciones son la dependencia de archivos y servicios
externos, la ausencia de autenticación propia, el coste del bundle Plotly y la
validación científica aún incompleta del detector y de algunas heurísticas.

**[PENDIENTE: sustituir esta discusión cualitativa por métricas reproducibles de
latencia, memoria, tamaño de descarga y evaluación de usuarios.]**

## 11. Conclusiones

AstroDoncel Studio cumple el objetivo de convertir un conjunto de herramientas
de consulta y análisis e-CALLISTO en una aplicación web desplegable y
mantenible. La solución integra datos FITS, catálogo institucional, análisis
interactivo, tareas persistentes y exportación reproducible con controles de
seguridad y operación adecuados a un NAS.

El trabajo también delimita lo que no debe afirmarse: el detector no clasifica
tipos de burst y la medida visual de deriva no equivale a una estimación física
completa de eventos tipo II. Esta separación permite entregar una base sólida
sin presentar resultados científicos no validados.

## 12. Trabajo futuro

- cerrar licencia del proyecto y permiso de redistribución del modelo;
- construir y publicar el protocolo de validación científica;
- completar pruebas E2E de navegador en CI;
- medir rendimiento y consumo en el NAS;
- ensayar y documentar restauración completa;
- modularizar gradualmente los archivos principales;
- estudiar parámetros de bursts tipo II solo tras acordar con especialistas las
  definiciones, datos, incertidumbres y criterios de validación;
- añadir autenticación o roles si cambia el modelo de acceso.

## Referencias

1. e-CALLISTO, archivo y documentación de la red. **[PENDIENTE: referencia
   bibliográfica completa y fecha de consulta.]**
2. S. S. Liyanage, *e-CALLISTO FITS Analyzer*, artículo y repositorio de la
   versión de referencia. DOI: 10.1093/rasti/rzag056.
3. Documentación oficial de FITS/Astropy, FastAPI, React, Plotly, SQLAlchemy y
   Docker. **[PENDIENTE: adaptar al estilo bibliográfico exigido.]**

## Anexos previstos

- A. Manual de mantenimiento (`MANUAL_MANTENIMIENTO.md`).
- B. Diccionario de variables y endpoints principales.
- C. Modelo de datos y migraciones.
- D. Protocolo de pruebas y resultados de CI.
- E. Capturas de la versión etiquetada.
- F. Registro de procedencia y ficha del modelo.
