# -*- coding: utf-8 -*-
"""
API de VIGÍA Chillón — evidencia TRL 4.

Sirve la base analítica, el índice territorial y el modelo base distrital.
El riesgo NO está precalculado: se computa en cada petición a partir de la
lluvia observada de la fecha solicitada y de los predictores de cada celda.

Documentación interactiva en /docs (OpenAPI).
Ejecución local:  uvicorn api.main:app --reload
"""
import hashlib, json, math, sqlite3, time
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

RAIZ = Path(__file__).resolve().parents[1]
BD = RAIZ / "datos" / "vigia.db"
ART = RAIZ / "modelo" / "artefactos"
WEB = RAIZ / "web"

CLASES = [("Bajo", 0.25), ("Medio", 0.45), ("Alto", 0.65), ("Muy alto", 1.01)]

app = FastAPI(
    title="VIGÍA Chillón — API",
    version="0.1.0",
    description=(
        "Servicio de anticipación y clasificación del riesgo de inundación por celdas de 500 m "
        "en el distrito de Puente Piedra. Prototipo de acreditación TRL 4: los valores se "
        "calculan en tiempo de petición a partir de datos reales (CHIRPS, MINAM, CENEPRED, "
        "PREDES, INEI). No sustituye los avisos oficiales de SENAMHI, INDECI, CENEPRED ni ANA."
    ),
    docs_url="/docs",
)


def conectar() -> sqlite3.Connection:
    if not BD.exists():
        raise HTTPException(503, "La base analítica no existe. Ejecute el pipeline antes de iniciar la API.")
    cx = sqlite3.connect(BD, check_same_thread=False)
    cx.row_factory = sqlite3.Row
    return cx


@lru_cache(maxsize=1)
def cargar_modelo():
    ruta = ART / "modelo.joblib"
    if not ruta.exists():
        raise HTTPException(503, "El modelo no está entrenado. Ejecute python -m modelo.entrenar")
    return joblib.load(ruta)


@lru_cache(maxsize=1)
def ficha_modelo() -> dict:
    ruta = ART / "ficha_modelo.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}


@lru_cache(maxsize=1)
def celdas_estaticas() -> list:
    cx = conectar()
    filas = [dict(r) for r in cx.execute("SELECT * FROM celdas ORDER BY fila, columna")]
    cx.close()
    return filas


def clase_de(v: float) -> str:
    for nombre, tope in CLASES:
        if v < tope:
            return nombre
    return CLASES[-1][0]


def fila_precip(cx, fecha: str) -> sqlite3.Row:
    r = cx.execute("SELECT * FROM precipitacion WHERE fecha = ?", (fecha,)).fetchone()
    if r is None:
        rango = cx.execute("SELECT MIN(fecha) a, MAX(fecha) b FROM precipitacion").fetchone()
        raise HTTPException(404, f"No hay datos para {fecha}. Rango disponible: {rango['a']} a {rango['b']}.")
    return r


def probabilidad_distrital(p: sqlite3.Row) -> Optional[float]:
    """Probabilidad del modelo PU para esa fecha; None si faltan acumulados."""
    paquete = cargar_modelo()
    rasgos, modelo = paquete["rasgos"], paquete["modelo"]
    valores = []
    for r in rasgos:
        base = r[1:] if r.startswith("lp_") else r
        v = p[base]
        if v is None:
            return None
        valores.append(math.log1p(v) if r.startswith("lp_") else v)
    return float(modelo.predict_proba(np.array([valores]))[0, 1])


@app.on_event("startup")
def precargar():
    """Carga el modelo y las celdas al arrancar para que la primera consulta no pague el arranque en frío."""
    try:
        cargar_modelo(); ficha_modelo(); celdas_estaticas()
        print("VIGÍA Chillón: modelo y base analítica precargados")
    except Exception as e:  # el servicio arranca igual y /api/salud reporta el estado
        print(f"AVISO al precargar: {e}")


@app.get("/api/salud", tags=["sistema"], summary="Estado del servicio y de sus componentes")
def salud():
    cx = conectar()
    meta = {r["clave"]: r["valor"] for r in cx.execute("SELECT * FROM metadatos")}
    n_celdas = cx.execute("SELECT COUNT(*) c FROM celdas").fetchone()["c"]
    rango = cx.execute("SELECT MIN(fecha) a, MAX(fecha) b FROM precipitacion").fetchone()
    cx.close()
    return {
        "estado": "operativo",
        "base_analitica": {"celdas": n_celdas, "serie": f"{rango['a']} a {rango['b']}"},
        "modelo": {"version": ficha_modelo().get("version"), "cargado": (ART / "modelo.joblib").exists()},
        "procedencia": {k: meta.get(k) for k in ("origen", "sha256_origen", "construido_utc")},
        "politicas": {k: meta.get(k) for k in ("politica_faltantes", "politica_negativos")},
    }


@app.get("/api/celdas", tags=["territorio"], summary="Las 260 celdas con sus predictores estáticos")
def celdas():
    cx = conectar()
    meta = {r["clave"]: r["valor"] for r in cx.execute("SELECT * FROM metadatos")}
    rio = [[r["x"], r["y"]] for r in cx.execute("SELECT * FROM rio ORDER BY orden")]
    fmax = cx.execute("SELECT MAX(fila) f, MAX(columna) c FROM celdas").fetchone()
    cx.close()
    return {
        "celdas": celdas_estaticas(),
        "rio": rio,
        "malla": {"fila_max": fmax["f"], "columna_max": fmax["c"], "lado_m": 500, "crs": meta.get("crs")},
        "fuente": "SDOT-PCM/INEI 2023; predictores MINAM, CENEPRED, PREDES, WorldPop, GHSL",
    }


@app.get("/api/puntos-criticos", tags=["territorio"], summary="Puntos críticos inventariados (PREDES 2022)")
def puntos_criticos():
    cx = conectar()
    filas = [dict(r) for r in cx.execute("SELECT * FROM puntos_criticos ORDER BY lat DESC")]
    cx.close()
    return {"puntos": filas, "fuente": "PREDES, Estudio de escenario de riesgo de Puente Piedra (2022)"}


@app.get("/api/precipitacion", tags=["clima"], summary="Serie diaria de lluvia de la cuenca del Chillón")
def precipitacion(
    desde: Optional[str] = Query(None, description="AAAA-MM-DD"),
    hasta: Optional[str] = Query(None, description="AAAA-MM-DD"),
    dias: int = Query(14, ge=1, le=400, description="si no se da 'desde', devuelve los N días hasta 'hasta'"),
):
    cx = conectar()
    if desde and hasta:
        q = "SELECT * FROM precipitacion WHERE fecha BETWEEN ? AND ? ORDER BY fecha"
        filas = [dict(r) for r in cx.execute(q, (desde, hasta))]
    else:
        fin = hasta or cx.execute("SELECT MAX(fecha) f FROM precipitacion").fetchone()["f"]
        q = "SELECT * FROM precipitacion WHERE fecha <= ? ORDER BY fecha DESC LIMIT ?"
        filas = [dict(r) for r in cx.execute(q, (fin, dias))][::-1]
    cx.close()
    return {"serie": filas, "producto": "UCSB CHIRPS, promedio zonal de la cuenca del río Chillón",
            "unidad": "mm/día"}


@app.get("/api/riesgo", tags=["riesgo"], summary="Riesgo por celda para una fecha, calculado en la petición")
def riesgo(fecha: str = Query(..., description="AAAA-MM-DD entre 2003-01-01 y 2026-07-31")):
    t0 = time.perf_counter()
    cx = conectar()
    p = fila_precip(cx, fecha)
    evento = cx.execute("SELECT * FROM eventos WHERE fecha = ?", (fecha,)).fetchone()
    cx.close()

    prob = probabilidad_distrital(p)
    if prob is None:
        raise HTTPException(422, f"La fecha {fecha} no tiene acumulados completos (inicio de la serie).")

    # intensidad climática del día, normalizada contra un umbral operativo de 20 mm en 3 días
    intensidad = min(1.0, (p["p_3d"] or 0) / 20.0) * 0.6 + min(1.0, prob * 2.5) * 0.4
    celdas_r = []
    for c in celdas_estaticas():
        v = min(1.0, c["susceptibilidad"] * (0.30 + 0.70 * intensidad))
        celdas_r.append({"spatial_id": c["spatial_id"], "indice": round(v, 4), "clase": clase_de(v)})

    altas = [c for c in celdas_r if c["indice"] >= 0.45]
    pobl = sum(e["poblacion"] or 0 for e in celdas_estaticas()
               if e["spatial_id"] in {a["spatial_id"] for a in altas})

    return {
        "fecha": fecha,
        "precipitacion": {k: p[k] for k in ("p_t0", "p_1d", "p_3d", "p_7d", "p_14d", "p_30d")},
        "distrital": {
            "probabilidad_modelo": round(prob, 4),
            "intensidad_climatica": round(intensidad, 4),
            "clase": clase_de(intensidad),
        },
        "celdas": celdas_r,
        "resumen": {
            "celdas_alto_o_muy_alto": len(altas),
            "poblacion_en_esas_celdas": int(round(pobl)),
            "celdas_totales": len(celdas_r),
        },
        "evento_registrado": dict(evento) if evento else None,
        "modelo": {"version": ficha_modelo().get("version"),
                   "unidad": "distrito–día",
                   "advertencia": "índice por celda derivado de reglas; el modelo celda–día es el objetivo del proyecto"},
        "calculo_ms": round((time.perf_counter() - t0) * 1000, 2),
    }


@app.get("/api/celda/{spatial_id}", tags=["riesgo"], summary="Detalle de una celda y descomposición de su índice")
def celda(spatial_id: str, fecha: Optional[str] = Query(None, description="AAAA-MM-DD")):
    c = next((x for x in celdas_estaticas() if x["spatial_id"] == spatial_id), None)
    if c is None:
        raise HTTPException(404, f"No existe la celda {spatial_id}")
    salida = {"celda": c}
    if fecha:
        r = riesgo(fecha)
        mio = next(x for x in r["celdas"] if x["spatial_id"] == spatial_id)
        salida["riesgo"] = {"fecha": fecha, **mio}
        salida["factores"] = {
            "cercania_al_rio": round(1 - min(1, (c["dist_rio_m"] or 0) / 2500), 3),
            "terreno_plano": round(1 - min(1, (c["pendiente_grados"] or 0) / 12), 3),
            "cota_baja": round(1 - min(1, max(0, (c["elev_media_m"] or 0) - 60) / 200), 3),
            "drenaje": round(min(1, (c["drenaje_m"] or 0) / 2500), 3),
            "canales": round(min(1, (c["canales_n"] or 0) / 6), 3),
            "intensidad_climatica": r["distrital"]["intensidad_climatica"],
        }
    return salida


@app.get("/api/eventos", tags=["riesgo"], summary="Positivos corroborados (sin negativos verificados)")
def eventos():
    cx = conectar()
    filas = [dict(r) for r in cx.execute("SELECT * FROM eventos ORDER BY fecha")]
    cx.close()
    return {
        "eventos": filas,
        "negativos_verificados": 0,
        "nota": ("La ausencia de reporte no equivale a ausencia de evento. Los días sin positivo "
                 "son NO ETIQUETADOS. Los negativos se producirán con la bitácora de vigías."),
    }


@app.get("/api/campo-simulado", tags=["campo"],
         summary="SIMULADO: reportes ciudadanos y bitácora de vigías del piloto previsto")
def campo_simulado(fecha: str = Query(..., description="AAAA-MM-DD")):
    """
    Estos datos NO son observaciones reales: el trabajo de campo es el objeto del
    proyecto y todavía no existe. Se generan de forma determinista a partir de la
    lluvia realmente observada en cada fecha para ilustrar cómo se vería el bucle
    de aprendizaje en operación. El nombre del recurso lo declara explícitamente.
    """
    cx = conectar()
    p = fila_precip(cx, fecha)
    # los siete días previos, con su lluvia real: la bitácora reacciona a datos verdaderos
    previos = [dict(r) for r in cx.execute(
        "SELECT fecha, p_t0, p_3d FROM precipitacion WHERE fecha <= ? ORDER BY fecha DESC LIMIT 7",
        (fecha,))][::-1]
    puntos = [dict(r) for r in cx.execute("SELECT * FROM puntos_criticos ORDER BY lat DESC")]
    cx.close()

    def dado(*partes) -> float:
        """Sorteo determinista en [0,1): la misma fecha devuelve siempre lo mismo."""
        h = hashlib.sha256("|".join(str(x) for x in partes).encode()).hexdigest()
        return int(h[:8], 16) / 0xFFFFFFFF

    # --- bitácora: 8 puntos x 7 días ---
    bitacora = []
    for i, pt in enumerate(puntos):
        celdas_dia = []
        for d in previos:
            lluvia = d["p_3d"] or 0
            r = dado(d["fecha"], pt["codigo"])
            if lluvia >= 12 and r < 0.35:
                estado = "desborde"
            elif lluvia >= 6 and r < 0.55:
                estado = "nivel_alto"
            elif lluvia >= 2 and r < 0.30:
                estado = "nivel_alto"
            else:
                estado = "sin_novedad"
            celdas_dia.append({"fecha": d["fecha"], "estado": estado,
                               "lluvia_3d_mm": round(lluvia, 2)})
        bitacora.append({"punto": pt["nombre"], "codigo": pt["codigo"], "dias": celdas_dia})

    negativos = sum(1 for b in bitacora for d in b["dias"] if d["estado"] == "sin_novedad")
    positivos = sum(1 for b in bitacora for d in b["dias"] if d["estado"] == "desborde")

    # --- reportes ciudadanos: su número crece con la lluvia observada ---
    CATALOGO = [
        ("🌊", "Aniego en vía", "inundacion"),
        ("🌊", "Agua ingresa a viviendas", "inundacion"),
        ("🪵", "Canal obstruido con desmonte", "obstruccion"),
        ("🪵", "Acumulación de residuos en dren", "obstruccion"),
        ("🧱", "Muro de defensa con filtración", "infraestructura"),
        ("⚠️", "Erosión de ribera", "erosion"),
        ("🔥", "Quema de residuos junto al cauce", "mala_practica"),
        ("🌊", "Calle inundada frente a la I.E.", "inundacion"),
    ]
    ESTADOS = ["verificado", "en_verificacion", "en_atencion"]
    lluvia3 = p["p_3d"] or 0
    n = 2 if lluvia3 < 1 else 4 if lluvia3 < 6 else 7 if lluvia3 < 12 else 9
    horas = ["hace 40 min", "hace 1 h", "hace 2 h", "hace 3 h", "hace 5 h",
             "hace 6 h", "hace 8 h", "ayer", "ayer"]
    reportes = []
    for k in range(n):
        r = dado(fecha, "rep", k)
        ic, titulo, tipo = CATALOGO[int(dado(fecha, "cat", k) * len(CATALOGO))]
        pt = puntos[int(r * len(puntos))]
        # con poca lluvia predominan las malas prácticas; con mucha, las inundaciones
        if lluvia3 < 2 and tipo == "inundacion":
            ic, titulo, tipo = CATALOGO[6]
        reportes.append({
            "icono": ic, "titulo": titulo, "tipo": tipo,
            "sector": pt["nombre"], "hora": horas[k % len(horas)],
            "estado": ESTADOS[int(dado(fecha, "est", k) * 3)],
        })

    return {
        "naturaleza": "SIMULADO",
        "advertencia": ("Datos ilustrativos generados de forma determinista a partir de la "
                        "lluvia observada. No son observaciones de campo: la red de vigías y "
                        "el canal ciudadano son el objeto del proyecto."),
        "fecha": fecha,
        "reportes": reportes,
        "bitacora": bitacora,
        "etiquetas_que_produciria": {
            "negativos_verificados": negativos,
            "positivos_de_campo": positivos,
            "reportes_verificados": sum(1 for r in reportes if r["estado"] != "en_verificacion"),
            "nota": "así es como la bitácora generaría las etiquetas que hoy no existen",
        },
    }


@app.get("/api/modelo", tags=["sistema"], summary="Ficha del modelo: métricas, límites y usos previstos")
def modelo():
    f = ficha_modelo()
    if not f:
        raise HTTPException(503, "El modelo no está entrenado.")
    return f


@app.get("/", include_in_schema=False)
def inicio():
    indice = WEB / "index.html"
    if indice.exists():
        return FileResponse(indice)
    return JSONResponse({"servicio": "VIGÍA Chillón API", "documentacion": "/docs"})


if WEB.exists():
    app.mount("/web", StaticFiles(directory=WEB, html=True), name="web")
