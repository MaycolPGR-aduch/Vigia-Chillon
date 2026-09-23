# -*- coding: utf-8 -*-
"""
Pruebas de integración de VIGÍA Chillón.

Demuestran que los cuatro componentes funcionan encadenados:
base analítica -> índice territorial -> modelo -> API -> tablero.

Ejecución:  pytest -v
"""
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app

RAIZ = Path(__file__).resolve().parents[1]
BD = RAIZ / "datos" / "vigia.db"
cliente = TestClient(app)


# ---------------------------------------------------------------- base de datos
def test_base_analitica_existe():
    assert BD.exists(), "falta datos/vigia.db; ejecute el pipeline"


def test_malla_completa():
    cx = sqlite3.connect(BD)
    n = cx.execute("SELECT COUNT(*) FROM celdas").fetchone()[0]
    cx.close()
    assert n == 260, f"se esperaban 260 celdas, hay {n}"


def test_serie_diaria_sin_huecos():
    cx = sqlite3.connect(BD)
    fechas = [r[0] for r in cx.execute("SELECT fecha FROM precipitacion ORDER BY fecha")]
    cx.close()
    import datetime as dt
    d = [dt.date.fromisoformat(f) for f in fechas]
    huecos = [(a, b) for a, b in zip(d, d[1:]) if (b - a).days != 1]
    assert not huecos, f"la serie tiene huecos: {huecos[:3]}"
    assert len(d) == 8613


def test_no_existen_negativos_verificados():
    """Regla metodológica: ningún día puede estar marcado como negativo."""
    cx = sqlite3.connect(BD)
    meta = dict(cx.execute("SELECT clave, valor FROM metadatos").fetchall())
    cx.close()
    assert meta["negativos_verificados"] == "0"
    assert "NO ETIQUETADOS" in meta["politica_negativos"]


def test_faltantes_no_se_imputan():
    """Los primeros días de la serie deben conservar NULL en los acumulados."""
    cx = sqlite3.connect(BD)
    n = cx.execute("SELECT COUNT(*) FROM precipitacion WHERE p_30d IS NULL").fetchone()[0]
    cx.close()
    assert n > 0, "los acumulados iniciales deberían ser NULL, no cero"


# ---------------------------------------------------------------- modelo
def test_ficha_modelo_declara_limites():
    f = json.loads((RAIZ / "modelo" / "artefactos" / "ficha_modelo.json").read_text(encoding="utf-8"))
    assert f["negativos_verificados"] == 0
    for m in ("exactitud", "especificidad", "tasa de falsos positivos"):
        assert m in f["metricas_no_reportables"]
    assert len(f["limitaciones"]) >= 5


def test_modelo_ordena_por_encima_del_azar():
    """El percentil mediano de los positivos debe superar claramente al azar (50)."""
    f = json.loads((RAIZ / "modelo" / "artefactos" / "ficha_modelo.json").read_text(encoding="utf-8"))
    assert f["metricas"]["percentil_mediano"] > 60


# ---------------------------------------------------------------- API
def test_salud():
    r = cliente.get("/api/salud")
    assert r.status_code == 200
    j = r.json()
    assert j["estado"] == "operativo"
    assert j["base_analitica"]["celdas"] == 260
    assert j["procedencia"]["sha256_origen"]


def test_celdas_trae_predictores_y_rio():
    j = cliente.get("/api/celdas").json()
    assert len(j["celdas"]) == 260
    c = j["celdas"][0]
    for campo in ("spatial_id", "lon", "lat", "dist_rio_m", "susceptibilidad", "exposicion"):
        assert campo in c, f"falta {campo}"
    assert len(j["rio"]) > 10


@pytest.mark.parametrize("fecha", ["2023-03-11", "2017-03-16", "2015-08-03", "2005-03-31"])
def test_riesgo_se_calcula_para_cualquier_fecha(fecha):
    j = cliente.get("/api/riesgo", params={"fecha": fecha}).json()
    assert j["fecha"] == fecha
    assert len(j["celdas"]) == 260
    assert 0 <= j["distrital"]["probabilidad_modelo"] <= 1
    assert all(0 <= c["indice"] <= 1 for c in j["celdas"])


def test_dia_lluvioso_supera_a_dia_seco():
    """Prueba funcional del encadenamiento: más lluvia observada, más celdas en riesgo."""
    lluvioso = cliente.get("/api/riesgo", params={"fecha": "2023-03-11"}).json()
    seco = cliente.get("/api/riesgo", params={"fecha": "2015-08-03"}).json()
    assert lluvioso["precipitacion"]["p_3d"] > seco["precipitacion"]["p_3d"]
    assert (lluvioso["resumen"]["celdas_alto_o_muy_alto"]
            > seco["resumen"]["celdas_alto_o_muy_alto"])


def test_riesgo_es_determinista():
    a = cliente.get("/api/riesgo", params={"fecha": "2023-03-11"}).json()
    b = cliente.get("/api/riesgo", params={"fecha": "2023-03-11"}).json()
    assert [c["indice"] for c in a["celdas"]] == [c["indice"] for c in b["celdas"]]


def test_fecha_fuera_de_rango_devuelve_404():
    r = cliente.get("/api/riesgo", params={"fecha": "1999-01-01"})
    assert r.status_code == 404
    assert "Rango disponible" in r.json()["detail"]


def test_celda_inexistente_devuelve_404():
    assert cliente.get("/api/celda/NO_EXISTE").status_code == 404


def test_detalle_de_celda_descompone_factores():
    j = cliente.get("/api/celda/PP0500_R0011_C0014", params={"fecha": "2023-03-11"}).json()
    assert j["celda"]["spatial_id"] == "PP0500_R0011_C0014"
    assert "riesgo" in j and "factores" in j
    assert set(j["factores"]) >= {"cercania_al_rio", "terreno_plano", "drenaje", "canales"}


def test_campo_simulado_declara_su_naturaleza():
    j = cliente.get("/api/campo-simulado", params={"fecha": "2023-03-11"}).json()
    assert j["naturaleza"] == "SIMULADO"
    assert "No son observaciones de campo" in j["advertencia"]
    assert len(j["bitacora"]) == 8 and len(j["bitacora"][0]["dias"]) == 7


def test_campo_simulado_es_determinista():
    a = cliente.get("/api/campo-simulado", params={"fecha": "2023-03-11"}).json()
    b = cliente.get("/api/campo-simulado", params={"fecha": "2023-03-11"}).json()
    assert a == b


def test_bitacora_reacciona_a_la_lluvia_real():
    """En estiaje la bitácora debe producir solo negativos; con lluvias, positivos."""
    seco = cliente.get("/api/campo-simulado", params={"fecha": "2015-08-03"}).json()
    lluvioso = cliente.get("/api/campo-simulado", params={"fecha": "2023-03-11"}).json()
    assert seco["etiquetas_que_produciria"]["positivos_de_campo"] == 0
    assert lluvioso["etiquetas_que_produciria"]["positivos_de_campo"] > 0
    assert (seco["etiquetas_que_produciria"]["negativos_verificados"]
            > lluvioso["etiquetas_que_produciria"]["negativos_verificados"])
    assert len(lluvioso["reportes"]) > len(seco["reportes"])


def test_tablero_pinta_los_paneles_de_campo():
    """Regresión: los paneles de campo existían en el HTML pero nadie los llenaba."""
    html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="feed"' in html and 'id="bit"' in html
    assert "pintaCampo" in html, "falta la función que llena los paneles de campo"
    assert "/api/campo-simulado" in html


def test_eventos_sin_negativos():
    j = cliente.get("/api/eventos").json()
    assert len(j["eventos"]) == 8
    assert j["negativos_verificados"] == 0


def test_openapi_documentado():
    j = cliente.get("/openapi.json").json()
    rutas = set(j["paths"])
    for r in ("/api/salud", "/api/celdas", "/api/riesgo", "/api/modelo"):
        assert r in rutas


# ---------------------------------------------------------------- tablero
def test_tablero_no_incrusta_datos():
    """El tablero debe pedir los datos a la API, no traerlos dentro."""
    html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
    cabecera = html.split("<script>")[0]
    assert "PP0500_R00" not in cabecera, "el tablero incrusta identificadores de celda"
    assert "/api/riesgo" in html and "/api/celdas" in html


def test_guia_se_sirve_y_explica_el_sistema():
    r = cliente.get("/guia")
    assert r.status_code == 200
    for pieza in ("Arquitectura", "Modelo de datos", "Qué es real y qué es simulado",
                  "hoja de ruta", "bucle"):
        assert pieza.lower() in r.text.lower(), f"la guía no menciona: {pieza}"


def test_navegacion_entre_paginas():
    """Las dos páginas deben enlazarse entre sí y con la documentación."""
    for ruta in ("/", "/guia"):
        html = cliente.get(ruta).text
        assert 'href="/guia"' in html and 'href="/docs"' in html, f"falta navegación en {ruta}"


def test_guia_no_incrusta_cifras():
    """La guía también debe leer sus cifras de la API."""
    html = (RAIZ / "web" / "guia.html").read_text(encoding="utf-8")
    assert "/api/salud" in html and "/api/modelo" in html


def test_geojson_cumple_el_estandar():
    j = cliente.get("/api/geojson", params={"fecha": "2023-03-11"}).json()
    assert j["type"] == "FeatureCollection"
    tipos = {}
    for f in j["features"]:
        assert f["type"] == "Feature" and "geometry" in f and "properties" in f
        tipos[f["geometry"]["type"]] = tipos.get(f["geometry"]["type"], 0) + 1
    assert tipos["Polygon"] == 260, "faltan celdas"
    assert tipos["Point"] == 8, "faltan puntos críticos"
    assert tipos["LineString"] == 1, "falta la traza del río"


def test_geojson_incorpora_el_riesgo_solo_con_fecha():
    con = cliente.get("/api/geojson", params={"fecha": "2023-03-11"}).json()
    sin = cliente.get("/api/geojson").json()
    celda_con = next(f for f in con["features"] if f["geometry"]["type"] == "Polygon")
    celda_sin = next(f for f in sin["features"] if f["geometry"]["type"] == "Polygon")
    assert "clase_riesgo" in celda_con["properties"]
    assert "clase_riesgo" not in celda_sin["properties"]


def test_rio_pasa_por_los_puntos_criticos():
    """La traza debe coincidir con los puentes, que son estructuras sobre el cauce."""
    j = cliente.get("/api/geojson").json()
    rio = next(f for f in j["features"] if f["geometry"]["type"] == "LineString")
    vertices = {(round(x, 6), round(y, 6)) for x, y in rio["geometry"]["coordinates"]}
    puntos = [f for f in j["features"] if f["geometry"]["type"] == "Point"]
    for p in puntos:
        x, y = p["geometry"]["coordinates"]
        assert (round(x, 6), round(y, 6)) in vertices, f"{p['properties']['nombre']} no está en la traza"


def test_mapa_se_sirve_y_consume_la_api():
    r = cliente.get("/mapa")
    assert r.status_code == 200
    assert "/api/geojson" in r.text, "el mapa debe pedir los datos a la API"
    assert "leaflet" in r.text.lower()
    assert 'name="viewport"' in r.text


def test_navegacion_incluye_el_mapa():
    for ruta in ("/", "/mapa", "/guia"):
        html = cliente.get(ruta).text
        assert 'href="/mapa"' in html, f"falta el enlace al mapa en {ruta}"


def test_tablero_es_un_documento_html_completo():
    """Regresión: sin <meta viewport> los móviles renderizan a 980 px y recortan."""
    html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert 'name="viewport"' in html and "width=device-width" in html
    assert "<html" in html and "</html>" in html


def test_tablero_se_sirve():
    r = cliente.get("/")
    assert r.status_code == 200
    assert "VIGÍA Chillón" in r.text
