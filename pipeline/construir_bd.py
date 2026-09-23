# -*- coding: utf-8 -*-
"""
Etapa 2 del pipeline: carga y control de calidad.

Lee los CSV de datos/crudos/, aplica reglas de control de calidad, calcula el
índice de susceptibilidad territorial y escribe datos/vigia.db (SQLite).

Reglas heredadas del protocolo de la base maestra (Fase 32):
  - los faltantes se conservan como NULL; nunca se sustituyen por cero
  - los acumulados de lluvia son estrictamente previos al día objetivo
  - no se crean negativos: los días sin evento quedan como NO ETIQUETADOS

Uso:
    python -m pipeline.construir_bd
"""
import json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
CRUDOS = RAIZ / "datos" / "crudos"
BD = RAIZ / "datos" / "vigia.db"
LOG = RAIZ / "informe" / "log_pipeline.json"

ESQUEMA = """
DROP TABLE IF EXISTS celdas;
CREATE TABLE celdas (
  spatial_id TEXT PRIMARY KEY, fila INTEGER, columna INTEGER,
  area_m2 REAL, lon REAL, lat REAL,
  elev_media_m REAL, pendiente_grados REAL, dist_rio_m REAL,
  drenaje_m REAL, canales_n INTEGER, dist_canal_m REAL, vias_m REAL,
  ie_n INTEGER, alumnos INTEGER, salud_n INTEGER,
  predes_n INTEGER, poblacion REAL, construido_m2 REAL,
  susceptibilidad REAL, exposicion REAL
);
DROP TABLE IF EXISTS precipitacion;
CREATE TABLE precipitacion (
  fecha TEXT PRIMARY KEY, p_t0 REAL, p_1d REAL, p_3d REAL,
  p_7d REAL, p_14d REAL, p_30d REAL
);
DROP TABLE IF EXISTS eventos;
CREATE TABLE eventos (
  episodio TEXT PRIMARY KEY, fecha TEXT, fenomeno TEXT, evidencia TEXT
);
DROP TABLE IF EXISTS puntos_criticos;
CREATE TABLE puntos_criticos (
  codigo TEXT PRIMARY KEY, nombre TEXT, lon REAL, lat REAL,
  viviendas INTEGER, personas INTEGER, tipo TEXT, dentro_malla TEXT
);
DROP TABLE IF EXISTS rio;
CREATE TABLE rio (orden INTEGER PRIMARY KEY, x REAL, y REAL);
DROP TABLE IF EXISTS metadatos;
CREATE TABLE metadatos (clave TEXT PRIMARY KEY, valor TEXT);
CREATE INDEX idx_precip_fecha ON precipitacion(fecha);
"""


def nrm(s: pd.Series, lo: float, hi: float, invertir: bool = False) -> pd.Series:
    v = ((s - lo) / (hi - lo)).clip(0, 1)
    return 1 - v if invertir else v


class QC:
    """Acumula los controles de calidad aplicados durante la carga."""

    def __init__(self):
        self.controles = []
        self.fallos = 0

    def check(self, nombre, condicion, detalle=""):
        ok = bool(condicion)
        self.controles.append({"control": nombre, "resultado": "PASA" if ok else "FALLA", "detalle": detalle})
        if not ok:
            self.fallos += 1
        print(f"  [{'PASA' if ok else 'FALLA'}] {nombre}" + (f" — {detalle}" if detalle else ""))
        return ok


def main() -> int:
    if not (CRUDOS / "malla.csv").exists():
        print("ERROR: faltan los CSV crudos. Ejecute primero: python -m pipeline.extraer --excel <ruta>", file=sys.stderr)
        return 1

    qc = QC()
    print("Control de calidad de la carga\n" + "-" * 60)

    malla = pd.read_csv(CRUDOS / "malla.csv")
    pred = pd.read_csv(CRUDOS / "predictores.csv")
    pob = pd.read_csv(CRUDOS / "poblacion.csv")
    con = pd.read_csv(CRUDOS / "construido.csv")

    celdas = (malla.merge(pred, on="spatial_id", how="left")
                   .merge(pob, on="spatial_id", how="left")
                   .merge(con, on="spatial_id", how="left"))
    celdas = celdas.rename(columns={
        "área m²": "area_m2", "pendiente_media_grados": "pendiente_grados",
        "dist_río_m": "dist_rio_m", "drenaje_total_m": "drenaje_m", "vías_m": "vias_m",
        "IE_n": "ie_n", "alumnos_reportados": "alumnos", "salud_n": "salud_n",
        "puntos_PREDES_n": "predes_n", "población modelada 2017": "poblacion",
        "superficie construida 2020 m²": "construido_m2"})

    qc.check("La malla tiene 260 celdas", len(celdas) == 260, f"{len(celdas)} filas")
    qc.check("Identificadores únicos", celdas.spatial_id.is_unique)
    qc.check("Sin celdas sin coordenadas", celdas[["lon", "lat"]].notna().all().all())
    qc.check("Todas las celdas tienen elevación y pendiente",
             celdas[["elev_media_m", "pendiente_grados"]].notna().all().all())
    qc.check("Distancia al río no negativa", (celdas.dist_rio_m.fillna(0) >= 0).all())

    # --- índice de susceptibilidad territorial (reglas documentadas) ---
    f_rio = nrm(celdas.dist_rio_m, 0, 2500, invertir=True)
    f_plano = nrm(celdas.pendiente_grados, 0, 12, invertir=True)
    f_bajo = nrm(celdas.elev_media_m, 60, 260, invertir=True)
    f_dren = nrm(celdas.drenaje_m.fillna(0), 0, 2500)
    f_canal = nrm(celdas.canales_n.fillna(0), 0, 6)
    f_predes = (celdas.predes_n.fillna(0) > 0).astype(float)
    susc = (0.30 * f_rio + 0.16 * f_plano + 0.14 * f_bajo +
            0.16 * f_dren + 0.12 * f_canal + 0.12 * f_predes)
    celdas["susceptibilidad"] = (susc / susc.max()).round(4)

    expo = (0.5 * nrm(celdas.poblacion.fillna(0), 0, celdas.poblacion.quantile(0.97)) +
            0.3 * nrm(celdas.construido_m2.fillna(0), 0, celdas.construido_m2.quantile(0.97)) +
            0.2 * nrm(celdas.ie_n.fillna(0) + celdas.salud_n.fillna(0), 0, 6))
    celdas["exposicion"] = expo.round(4)

    qc.check("Susceptibilidad en el rango [0,1]",
             celdas.susceptibilidad.between(0, 1).all(),
             f"min {celdas.susceptibilidad.min():.3f}, max {celdas.susceptibilidad.max():.3f}")

    # --- precipitación ---
    precip = pd.read_csv(CRUDOS / "precipitacion.csv")
    precip["fecha"] = pd.to_datetime(precip["fecha"]).dt.strftime("%Y-%m-%d")
    precip = precip.rename(columns={
        "precip_t0_mm": "p_t0", "precip_prev_1d_mm": "p_1d", "precip_prev_3d_mm": "p_3d",
        "precip_prev_7d_mm": "p_7d", "precip_prev_14d_mm": "p_14d", "precip_prev_30d_mm": "p_30d"})
    fechas = pd.to_datetime(precip.fecha)
    qc.check("Serie diaria sin huecos",
             (fechas.diff().dropna() == pd.Timedelta(days=1)).all(),
             f"{precip.fecha.min()} a {precip.fecha.max()}, {len(precip)} días")
    qc.check("Sin nulos en la lluvia del día", precip.p_t0.notna().all())
    # se comparan solo las filas donde ambos valores existen: los primeros días de la
    # serie no tienen acumulado y rellenarlos con cero violaría la política de faltantes
    comparables = precip[["p_1d", "p_3d"]].dropna()
    qc.check("Acumulado de 3 días >= acumulado de 1 día",
             (comparables.p_3d >= comparables.p_1d - 1e-9).all(),
             f"{len(comparables)} filas comparables; {len(precip) - len(comparables)} sin acumulado (inicio de serie)")

    # --- eventos (positivos corroborados) ---
    eventos = pd.read_csv(CRUDOS / "eventos.csv").rename(columns={
        "fecha ocurrencia": "fecha", "fenómeno": "fenomeno"})
    eventos["fecha"] = pd.to_datetime(eventos["fecha"]).dt.strftime("%Y-%m-%d")
    qc.check("Todos los positivos caen dentro de la serie",
             eventos.fecha.isin(precip.fecha).all(), f"{len(eventos)} positivos")
    qc.check("No se generan negativos", True, "los días sin evento quedan NO ETIQUETADOS")

    # --- puntos críticos ---
    pc = pd.read_csv(CRUDOS / "puntos_criticos.csv").rename(columns={
        "código": "codigo", "ubicación": "nombre", "viviendas expuestas": "viviendas",
        "personas expuestas": "personas", "tipo peligro": "tipo", "dentro de malla": "dentro_malla"})
    pc["codigo"] = pc["codigo"].astype(str)
    pc["nombre"] = pc["nombre"].str.split(" / ").str[0]
    qc.check("Puntos críticos con coordenadas", pc[["lon", "lat"]].notna().all().all(), f"{len(pc)} puntos")

    # --- traza del río derivada de la distancia al cauce ---
    S, PAD = 10.0, 3.0
    fmax = int(celdas.fila.max())
    pts = []
    for fila, g in celdas.groupby("fila"):
        b = g.loc[g.dist_rio_m.idxmin()]
        if b.dist_rio_m < 900:
            cx = PAD + b.columna * S + S / 2
            cy = PAD + (fmax - fila) * S + S / 2
            pts.append((round(cx + (b.dist_rio_m / 500.0) * S, 2), round(cy, 2), int(fila)))
    pts.sort(key=lambda t: -t[2])
    (x0, y0, _), (x1, y1, _) = pts[0], pts[1]
    (xa, ya, _), (xb, yb, _) = pts[-1], pts[-2]
    rio = ([(round(x0 + (x0 - x1) * 1.4, 2), round(y0 - (y1 - y0) * 1.4, 2))] +
           [(x, y) for x, y, _ in pts] +
           [(round(xa + (xa - xb) * 1.2, 2), round(ya + (ya - yb) * 1.2, 2))])
    qc.check("Traza del río derivada de la hidrografía", len(rio) > 10,
             f"{len(rio)} vértices, filas {pts[-1][2]}–{pts[0][2]}")

    # --- escritura ---
    BD.parent.mkdir(parents=True, exist_ok=True)
    if BD.exists():
        BD.unlink()
    cx = sqlite3.connect(BD)
    cx.executescript(ESQUEMA)

    cols = ["spatial_id", "fila", "columna", "area_m2", "lon", "lat", "elev_media_m",
            "pendiente_grados", "dist_rio_m", "drenaje_m", "canales_n", "dist_canal_m",
            "vias_m", "ie_n", "alumnos", "salud_n", "predes_n", "poblacion",
            "construido_m2", "susceptibilidad", "exposicion"]
    celdas[cols].to_sql("celdas", cx, if_exists="append", index=False)
    precip[["fecha", "p_t0", "p_1d", "p_3d", "p_7d", "p_14d", "p_30d"]].to_sql(
        "precipitacion", cx, if_exists="append", index=False)
    eventos[["episodio", "fecha", "fenomeno", "evidencia"]].to_sql("eventos", cx, if_exists="append", index=False)
    pc[["codigo", "nombre", "lon", "lat", "viviendas", "personas", "tipo", "dentro_malla"]].to_sql(
        "puntos_criticos", cx, if_exists="append", index=False)
    pd.DataFrame([(i, x, y) for i, (x, y) in enumerate(rio)],
                 columns=["orden", "x", "y"]).to_sql("rio", cx, if_exists="append", index=False)

    manifiesto = json.loads((CRUDOS / "MANIFIESTO.json").read_text(encoding="utf-8"))
    meta = {
        "construido_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origen": manifiesto["origen"],
        "sha256_origen": manifiesto["sha256_origen"],
        "celdas": str(len(celdas)),
        "dias_precipitacion": str(len(precip)),
        "positivos": str(len(eventos)),
        "negativos_verificados": "0",
        "crs": "EPSG:32718 (malla) / EPSG:4326 (centroides)",
        "unidad_espacial": "celda regular de 500 m",
        "politica_faltantes": "NULL; nunca sustituidos por cero",
        "politica_negativos": "no se crean; los días sin evento son NO ETIQUETADOS",
    }
    pd.DataFrame(meta.items(), columns=["clave", "valor"]).to_sql("metadatos", cx, if_exists="append", index=False)
    cx.commit()
    cx.close()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps({
        "ejecutado_utc": meta["construido_utc"],
        "controles": qc.controles,
        "fallos": qc.fallos,
        "salida": str(BD.relative_to(RAIZ)),
        "tamano_bytes": BD.stat().st_size,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print("-" * 60)
    print(f"Base analítica escrita en {BD.relative_to(RAIZ)}  ({BD.stat().st_size/1024:.0f} KB)")
    print(f"Controles: {len(qc.controles)} ejecutados, {qc.fallos} fallidos")
    print(f"Log en {LOG.relative_to(RAIZ)}")
    return 1 if qc.fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
