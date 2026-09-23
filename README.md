# VIGÍA Chillón — prototipo de acreditación TRL 4

Sistema de anticipación y clasificación del riesgo de inundación por celdas de 500 m
en el distrito de Puente Piedra (Lima, Perú).

Este repositorio es la **evidencia ejecutable** que acredita el nivel de madurez
tecnológica TRL 4 exigido por el concurso PROCIENCIA E067-2026-04, modalidad
*Desarrollo, Validación, Transferencia y Uso*.

> **Qué demuestra.** Que los seis componentes del sistema funcionan encadenados sobre
> datos reales: fuentes → pipeline → índice territorial → modelo → API → tablero.
> El riesgo **no está precalculado**: se computa en cada petición con la lluvia
> observada de la fecha consultada.
>
> **Qué no demuestra.** No hay modelo por celda de 500 m entrenado con etiquetas de
> campo, porque no existen negativos verificados. Eso es el objeto del proyecto y
> corresponde al TRL 6 de salida.

---

## Comprobación en un minuto

Con el servicio publicado, cualquiera puede verificar que el cálculo es real:

```bash
# un día de lluvias intensas
curl "$URL/api/riesgo?fecha=2023-03-11" | jq '.distrital, .resumen'
# el mismo sistema en estiaje
curl "$URL/api/riesgo?fecha=2015-08-03" | jq '.distrital, .resumen'
```

El primero devuelve 45 celdas en nivel alto o muy alto; el segundo, ninguna. La
diferencia procede de la serie CHIRPS observada, no de valores fijos en la página.
En el tablero, el campo **«o cualquier fecha»** permite consultar cualquier día entre
el 31/01/2003 y el 31/07/2026.

---

## Estructura

```
vigia-trl4/
├── pipeline/          ETL en dos etapas con control de calidad
│   ├── extraer.py       base maestra (Excel) → CSV normalizados + manifiesto con SHA-256
│   └── construir_bd.py  CSV → SQLite, 13 controles de calidad, índice territorial
├── modelo/
│   ├── entrenar.py      modelo positivo–no etiquetado + validación dejando-uno-fuera
│   └── artefactos/      modelo.joblib, ficha_modelo.json, loo_detalle.json
├── api/main.py        servicio FastAPI; OpenAPI en /docs
├── web/index.html     tablero; no contiene datos del distrito, los pide a la API
├── tests/             22 pruebas de integración
├── informe/           log del pipeline e INFORME_PRUEBAS.md
└── datos/vigia.db     base analítica (260 celdas, 8 613 días)
```

## Ejecutar en local

```bash
python -m venv .venv && .venv\Scripts\activate        # Windows
pip install -r requirements-dev.txt

# 1. pipeline (solo si se quiere reconstruir la base desde el Excel)
python -m pipeline.extraer --excel "../Base_Maestra_FEN_Puente_Piedra_Modelo_Predictivo_Fase32.xlsx"
python -m pipeline.construir_bd

# 2. modelo
python -m modelo.entrenar

# 3. pruebas e informe de evidencia
python informe/generar_informe.py

# 4. servicio
uvicorn api.main:app --reload
```

Tablero en <http://127.0.0.1:8000/> · documentación de la API en <http://127.0.0.1:8000/docs>

La base `datos/vigia.db` y el modelo entrenado viajan en el repositorio, de modo que
los pasos 1 y 2 no son necesarios para levantar el servicio ni para desplegarlo.

---

## Publicar en la nube

El contenedor es autosuficiente: no necesita el Excel de origen ni reentrenar.

### Opción A — Render (la más simple)

1. Suba este directorio a un repositorio de GitHub.
2. En <https://render.com> → **New** → **Web Service** → conecte el repositorio.
3. Render detecta el `Dockerfile` y el `render.yaml`. Plan **Free**. Cree el servicio.
4. En tres o cuatro minutos queda publicado en `https://<nombre>.onrender.com`.

**Advertencia importante:** el plan gratuito de Render duerme el servicio tras 15 minutos
sin tráfico y el primer acceso tarda entre 30 y 60 segundos. Si el enlace va a estar en el
expediente, programe un ping cada 10 minutos a `/api/salud` con un servicio gratuito como
[cron-job.org](https://cron-job.org), o use la opción B.

### Opción B — Fly.io (no duerme)

```bash
fly auth login
fly launch --no-deploy      # respeta el fly.toml incluido
fly deploy
```

La región configurada es `scl` (Santiago), la más cercana a Lima.

### Opción C — Hugging Face Spaces (gratuito y estable para demostraciones)

1. Cree un Space de tipo **Docker**, visibilidad pública.
2. Suba el contenido del repositorio.
3. Añada `app_port: 8000` en la cabecera del `README.md` del Space.

### Opción D — Google Cloud Run

```bash
gcloud run deploy vigia-chillon --source . --region southamerica-west1 --allow-unauthenticated
```

---

## Recursos de la API

| Método | Ruta | Devuelve |
|---|---|---|
| GET | `/api/salud` | estado, procedencia de los datos con SHA-256 y políticas metodológicas |
| GET | `/api/celdas` | las 260 celdas con sus 22 predictores, la traza del río y la malla |
| GET | `/api/puntos-criticos` | los 8 puntos críticos de PREDES 2022 con coordenadas |
| GET | `/api/precipitacion` | serie diaria CHIRPS de la cuenca del Chillón |
| GET | `/api/riesgo?fecha=` | **índice y clase de las 260 celdas, calculado en la petición** |
| GET | `/api/celda/{id}?fecha=` | detalle de una celda y descomposición de su índice en factores |
| GET | `/api/campo-simulado?fecha=` | **SIMULADO**: reportes y bitácora del piloto previsto, generados de forma determinista a partir de la lluvia real |
| GET | `/api/eventos` | los 8 positivos corroborados; declara que no hay negativos |
| GET | `/api/modelo` | ficha del modelo: métricas, límites y usos previstos |
| GET | `/docs` | documentación interactiva OpenAPI |

---

## Reglas metodológicas que el código hace cumplir

Heredadas del protocolo de la base maestra (Fase 32) y verificadas por las pruebas:

- **Los faltantes se conservan como NULL.** Nunca se sustituyen por cero. Los primeros
  días de la serie no tienen acumulados y así se mantienen.
- **No se fabrican negativos.** La ausencia de reporte no equivale a ausencia de evento:
  los días sin positivo quedan como NO ETIQUETADOS. Por eso el modelo es
  positivo–no etiquetado y no un clasificador binario.
- **No se reportan exactitud, especificidad, precisión ni tasa de falsos positivos.**
  Sin negativos observados esas métricas no están definidas. Se informan el percentil
  mediano de los positivos y recall@k bajo validación dejando-uno-fuera.
- **Se declara el sesgo de selección.** La especificación del modelo se eligió con la
  misma validación que se reporta; con ocho positivos no es posible una selección
  independiente, de modo que la cifra es una cota optimista.
- **Trazabilidad.** Cada carga registra el SHA-256 del archivo de origen, la fecha de
  extracción y el resultado de los 13 controles de calidad.

## Qué es real y qué es simulado

| Elemento | Naturaleza |
|---|---|
| Malla, predictores, puntos críticos, lluvia CHIRPS, eventos SINPAD | **reales**, de la base maestra Fase 32 |
| Índice territorial y probabilidad del modelo | **calculados** en cada petición sobre esos datos |
| Reportes ciudadanos y bitácora de vigías | **simulados**, servidos por `/api/campo-simulado` |

Los datos de campo se generan de forma determinista a partir de la lluvia realmente
observada en cada fecha: en estiaje la bitácora produce solo jornadas sin novedad, y con
lluvias intensas aparecen niveles altos y desbordes. Ilustran cómo se vería el bucle de
aprendizaje en operación y cuántas etiquetas produciría, pero **no son observaciones**:
la red de vigías y el canal ciudadano son el objeto del proyecto.

## Fuentes de datos

CHIRPS v3 (UCSB) · GeoSINPAD (INDECI) · escenario FEN 2023 (CENEPRED/SIGRID) ·
estudio de riesgo PREDES 2022 · límite distrital SDOT-PCM/INEI 2023 · hidrografía y
DEM (MINAM, Terrain Tiles) · población WorldPop 2017 · superficie construida GHSL 2020 ·
índices ENSO (NOAA CPC / ERSSTv6).

## Aviso

Sistema de apoyo a la decisión municipal. **No sustituye los avisos oficiales de
SENAMHI, INDECI, CENEPRED ni ANA.** El índice por celda se deriva de reglas
hidroterritoriales documentadas y no constituye un pronóstico validado.
