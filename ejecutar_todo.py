# -*- coding: utf-8 -*-
"""Reconstruye toda la evidencia de principio a fin.  Uso: python ejecutar_todo.py [--excel RUTA]"""
import argparse, subprocess, sys, time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PASOS = [
    ("Extracción de fuentes", [sys.executable, "-m", "pipeline.extraer", "--excel", "{excel}"]),
    ("Carga y control de calidad", [sys.executable, "-m", "pipeline.construir_bd"]),
    ("Entrenamiento del modelo", [sys.executable, "-m", "modelo.entrenar"]),
    ("Pruebas e informe de evidencia", [sys.executable, "informe/generar_informe.py"]),
]

ap = argparse.ArgumentParser()
ap.add_argument("--excel", default="../Base_Maestra_FEN_Puente_Piedra_Modelo_Predictivo_Fase32.xlsx")
args = ap.parse_args()

fallos = 0
for i, (nombre, cmd) in enumerate(PASOS, 1):
    cmd = [c.format(excel=args.excel) for c in cmd]
    print(f"\n{'='*70}\n[{i}/{len(PASOS)}] {nombre}\n{'='*70}")
    t0 = time.time()
    r = subprocess.run(cmd, cwd=RAIZ)
    print(f"--> {'OK' if r.returncode == 0 else 'FALLÓ'} en {time.time()-t0:.1f} s")
    fallos += r.returncode != 0

print(f"\n{'='*70}")
if fallos:
    print(f"{fallos} paso(s) fallaron. Revise la salida anterior.")
else:
    print("Evidencia reconstruida. Levante el servicio con:")
    print("   uvicorn api.main:app --reload")
sys.exit(1 if fallos else 0)
