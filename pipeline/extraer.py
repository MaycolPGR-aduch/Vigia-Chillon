# -*- coding: utf-8 -*-
"""
Etapa 1 del pipeline: extracción.

Lee la base maestra (Excel, Fase 32) y escribe CSV normalizados en datos/crudos/.
Cada CSV conserva la hoja de origen y la fecha de extracción para trazabilidad.

Uso:
    python -m pipeline.extraer --excel "..\\Base_Maestra_FEN_Puente_Piedra_Modelo_Predictivo_Fase32.xlsx"
"""
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
CRUDOS = RAIZ / "datos" / "crudos"

# hoja de origen -> (nombre de salida, columnas que se conservan)
HOJAS = {
    "MALLA_INEI_2023_F18": ("malla", ["spatial_id", "fila", "columna", "área m²", "lon", "lat"]),
    "MATRIZ_CERT_F25": ("predictores", [
        "spatial_id", "elev_media_m", "pendiente_media_grados", "dist_río_m", "drenaje_total_m",
        "canales_n", "dist_canal_m", "vías_m", "IE_n", "alumnos_reportados", "salud_n",
        "puntos_PREDES_n", "personas_PREDES"]),
    "WORLDPOP_500M_F29": ("poblacion", ["spatial_id", "población modelada 2017"]),
    "GHSL_BUILT_500M_F30": ("construido", ["spatial_id", "superficie construida 2020 m²"]),
    "PRECIP_CUENCA_DIARIA": ("precipitacion", [
        "fecha", "precip_t0_mm", "precip_prev_1d_mm", "precip_prev_3d_mm",
        "precip_prev_7d_mm", "precip_prev_14d_mm", "precip_prev_30d_mm"]),
    "POSITIVOS_TEMPORALES_F28": ("eventos", ["episodio", "fecha ocurrencia", "fenómeno", "evidencia"]),
    "PUNTOS_CRITICOS_2022": ("puntos_criticos", [
        "código", "ubicación", "lon", "lat", "viviendas expuestas", "personas expuestas",
        "tipo peligro", "dentro de malla"]),
    "ENSO": ("enso", None),
}


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="Extrae las hojas de la base maestra a CSV normalizados.")
    ap.add_argument("--excel", required=True, help="ruta del archivo .xlsx de la base maestra")
    args = ap.parse_args()

    origen = Path(args.excel).resolve()
    if not origen.exists():
        print(f"ERROR: no se encuentra {origen}", file=sys.stderr)
        return 1

    CRUDOS.mkdir(parents=True, exist_ok=True)
    manifiesto = {
        "origen": origen.name,
        "sha256_origen": sha256(origen),
        "extraido_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tablas": {},
    }

    xl = pd.ExcelFile(origen)
    for hoja, (salida, columnas) in HOJAS.items():
        if hoja not in xl.sheet_names:
            print(f"  AVISO: la hoja {hoja} no existe en el origen; se omite")
            continue
        df = xl.parse(hoja)
        if columnas:
            faltan = [c for c in columnas if c not in df.columns]
            if faltan:
                print(f"  AVISO: {hoja} sin columnas {faltan}; se extraen las disponibles")
            df = df[[c for c in columnas if c in df.columns]]
        destino = CRUDOS / f"{salida}.csv"
        df.to_csv(destino, index=False, encoding="utf-8")
        manifiesto["tablas"][salida] = {
            "hoja_origen": hoja,
            "filas": int(len(df)),
            "columnas": list(df.columns),
            "sha256": sha256(destino),
        }
        print(f"  {hoja:28} -> {destino.name:20} {len(df):>6} filas")

    (CRUDOS / "MANIFIESTO.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nManifiesto escrito en {CRUDOS / 'MANIFIESTO.json'}")
    print(f"SHA-256 del origen: {manifiesto['sha256_origen'][:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
