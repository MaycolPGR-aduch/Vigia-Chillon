# Informe de pruebas controladas — VIGÍA Chillón

**Propósito.** Acreditar el nivel de madurez tecnológica TRL 4 exigido por el concurso PROCIENCIA E067-2026-04: componentes integrados y validados en entorno controlado.

- **Fecha de ejecución:** 23/09/2026 16:35 Hora est. Pacífico, Sudamérica
- **Entorno:** Python 3.10.0 sobre Windows 10
- **Versión del modelo:** `0.1.0-pu-distrital`
- **Origen de los datos:** `datos\vigia.db` construida desde `2003-01-31 a 2026-07-31`

## 1. Cadena de componentes verificada

| # | Componente | Artefacto | Estado |
|---|---|---|---|
| 1 | Extracción de fuentes | `pipeline/extraer.py` → `datos/crudos/*.csv` + `MANIFIESTO.json` | verificado |
| 2 | Carga y control de calidad | `pipeline/construir_bd.py` → `datos/vigia.db` | verificado |
| 3 | Índice territorial | `susceptibilidad` y `exposicion` por celda | verificado |
| 4 | Modelo base | `modelo/artefactos/modelo.joblib` | verificado |
| 5 | API | FastAPI, OpenAPI en `/docs` | verificado |
| 6 | Tablero | `web/index.html`, sin datos embebidos | verificado |

## 2. Control de calidad del pipeline

Ejecutado el 2026-09-23T20:30:27+00:00. **13 controles, 0 fallidos.**

| Control | Resultado | Detalle |
|---|---|---|
| La malla tiene 260 celdas | PASA | 260 filas |
| Identificadores únicos | PASA | — |
| Sin celdas sin coordenadas | PASA | — |
| Todas las celdas tienen elevación y pendiente | PASA | — |
| Distancia al río no negativa | PASA | — |
| Susceptibilidad en el rango [0,1] | PASA | min 0.000, max 1.000 |
| Serie diaria sin huecos | PASA | 2003-01-01 a 2026-07-31, 8613 días |
| Sin nulos en la lluvia del día | PASA | — |
| Acumulado de 3 días >= acumulado de 1 día | PASA | 8610 filas comparables; 3 sin acumulado (inicio de serie) |
| Todos los positivos caen dentro de la serie | PASA | 8 positivos |
| No se generan negativos | PASA | los días sin evento quedan NO ETIQUETADOS |
| Puntos críticos con coordenadas | PASA | 8 puntos |
| Traza del río derivada de la hidrografía | PASA | 16 vértices, filas 0–13 |

## 3. Pruebas automatizadas de integración

```
30 passed, 3 warnings in 1.96s
```

Cubren: existencia e integridad de la base analítica, políticas metodológicas (faltantes como NULL, ausencia de negativos), ficha del modelo, respuestas de todos los recursos de la API, manejo de errores, determinismo y ausencia de datos embebidos en el tablero. Reproducible con `pytest -v`.

## 4. Prueba funcional encadenada

Cada fila es una consulta real a `GET /api/riesgo`: el servidor lee la lluvia observada de esa fecha, la pasa por el modelo y calcula el índice de las 260 celdas.

| Fecha | Contexto | Lluvia 3 d (mm) | Probabilidad | Clase | Celdas alto/muy alto | Población | Evento en SINPAD | Cálculo |
|---|---|---|---|---|---|---|---|---|
| 2023-03-11 | lluvias del ciclón Yaku | 14.19 | 0.918 | Muy alto | 45 | 73 555 | no | 1.66 ms |
| 2017-03-16 | Niño Costero | 9.2 | 0.812 | Muy alto | 35 | 55 845 | sí | 1.6 ms |
| 2007-01-09 | evento registrado en SINPAD | 8.85 | 0.756 | Muy alto | 35 | 55 845 | sí | 1.45 ms |
| 2015-08-03 | estiaje, sin evento | 0 | 0.086 | Bajo | 0 | 0 | no | 1.27 ms |
| 2020-07-15 | invierno seco, sin evento | 0.09 | 0.097 | Bajo | 0 | 0 | no | 1.19 ms |

La progresión entre fechas lluviosas y secas confirma que el encadenamiento fuentes → modelo → índice → API responde a la señal climática real y no a valores fijos.

## 5. Rendimiento de la API

| Recurso | Ruta | Mediana | p95 |
|---|---|---|---|
| salud | `/api/salud` | 3.8 ms | 4.12 ms |
| celdas | `/api/celdas` | 13.1 ms | 15.33 ms |
| riesgo | `/api/riesgo?fecha=2023-03-11` | 6.06 ms | 7.44 ms |
| celda | `/api/celda/PP0500_R0011_C0014?fecha=2023-03-11` | 4.41 ms | 5.14 ms |
| precipitacion | `/api/precipitacion?hasta=2023-03-11&dias=14` | 3.55 ms | 5.0 ms |

## 6. Desempeño del modelo base

- Unidad de análisis: **distrito–día**
- Positivos corroborados: **8**; días no etiquetados: **8 575**
- Negativos verificados: **0**
- Especificación elegida: `D_log`
- Percentil mediano de los positivos (validación dejando-uno-fuera): **85.17**
- Recall@10 % de los días: **0.375**; recall@20 %: **0.625**

Comparación contra líneas base sin modelo:

| Indicador | Percentil mediano |
|---|---|
| lluvia acumulada `p_3d` | 76.36 |
| lluvia acumulada `p_7d` | 71.31 |
| lluvia acumulada `p_30d` | 75.76 |
| **modelo `D_log`** | **85.17** |

Comparación de especificaciones evaluadas (todas se reportan, no solo la elegida):

| Especificación | Rasgos | Percentil mediano | Recall@10 % |
|---|---|---|---|
| A_completa | p_t0, p_1d, p_3d, p_7d, p_14d, p_30d, mes_sin, mes_cos | 66.69 | 0.25 |
| B_solo_lluvia | p_t0, p_1d, p_3d, p_7d, p_14d, p_30d | 75.27 | 0.375 |
| C_corta | p_t0, p_3d, p_7d | 80.38 | 0.25 |
| D_log | lp_t0, lp_3d, lp_7d, lp_30d | 85.17 | 0.375 |

## 7. Métricas que no se reportan y por qué

No se informan **exactitud, especificidad, tasa de falsos positivos, precisión**. No existen negativos observados. Los días sin positivo son NO ETIQUETADOS, por lo que toda métrica que requiera negativos verdaderos carece de sentido.

## 8. Limitaciones declaradas

- El modelo opera a escala distrital, no por celda de 500 m.
- Ocho positivos corroborados: la incertidumbre de cualquier estimación es alta.
- La lluvia es de cuenca (CHIRPS) y no sustituye observación hidrológica local.
- No incorpora caudal observado: las series de SENAMHI están pendientes de gestión.
- Es una línea base para acreditar madurez, no el modelo territorial del proyecto.
- SESGO DE SELECCIÓN DECLARADO: la especificación se eligió comparando las cuatro alternativas con la misma validación dejando-uno-fuera que se reporta. Con ocho positivos no es posible una selección independiente, de modo que el percentil mediano informado debe leerse como una cota optimista.
- HALLAZGO: dos de los ocho positivos quedan mal ordenados por el modelo. El 26/01/2017 cae en el percentil 39 y el 20/05/2018 en el 68 pese a registrar 0.04 mm de lluvia acumulada en tres días. Son eventos que la lluvia de cuenca no explica, probablemente desbordes de canal o afectaciones muy localizadas. Es el argumento cuantitativo que sustenta el proyecto: el salto de desempeño exige etiquetas por celda producidas en campo, no más ajuste del modelo.

## 9. Conclusión

Los seis componentes operan encadenados en entorno controlado, con datos reales del distrito de Puente Piedra, control de calidad reproducible y pruebas automatizadas que pasan íntegramente. Con esta evidencia **se acredita** el nivel TRL 4 de entrada.

El modelo por celda de 500 m, la incorporación de negativos verificados y la validación en entorno operacional municipal constituyen el alcance del proyecto y corresponden al TRL 6 de salida.

---

*Documento generado automáticamente por `informe/generar_informe.py`. Reproducible ejecutando el pipeline, el entrenamiento y las pruebas en ese orden.*