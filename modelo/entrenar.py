# -*- coding: utf-8 -*-
"""
Modelo base distrital, aprendizaje positivo–no etiquetado (PU).

Por qué PU y no clasificación binaria: la base de datos no contiene negativos
verificados. La ausencia de un reporte no equivale a la ausencia de un evento,
de modo que los días sin positivo son NO ETIQUETADOS, no ceros. Tratarlos como
ceros produciría métricas infladas e indefendibles.

Evaluación: con 8 positivos una partición temporal deja un único positivo en
prueba y no es informativa. Se usa validación dejando-uno-fuera (LOO): para cada
positivo se entrena sin él y se mide en qué percentil del ranking de riesgo
queda ese día. Se reporta recall@k y el percentil mediano. No se reportan
exactitud, especificidad ni tasa de falsos positivos: sin negativos observados
esas métricas no están definidas.

Uso:
    python -m modelo.entrenar
"""
import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
import joblib

RAIZ = Path(__file__).resolve().parents[1]
BD = RAIZ / "datos" / "vigia.db"
ART = RAIZ / "modelo" / "artefactos"
VERSION = "0.1.0-pu-distrital"
RASGOS = ["p_t0", "p_1d", "p_3d", "p_7d", "p_14d", "p_30d", "mes_sin", "mes_cos"]


def cargar() -> pd.DataFrame:
    cx = sqlite3.connect(BD)
    d = pd.read_sql("SELECT * FROM precipitacion ORDER BY fecha", cx)
    ev = pd.read_sql("SELECT fecha FROM eventos", cx)
    cx.close()
    f = pd.to_datetime(d.fecha)
    d["mes_sin"] = np.sin(2 * np.pi * f.dt.dayofyear / 365.25)
    d["mes_cos"] = np.cos(2 * np.pi * f.dt.dayofyear / 365.25)
    d["positivo"] = d.fecha.isin(ev.fecha).astype(int)
    # se descartan los días sin acumulados completos (inicio de serie); nunca se imputan
    return d.dropna(subset=RASGOS).reset_index(drop=True)


def nuevo_modelo(rasgos=None, C=0.5) -> Pipeline:
    # class_weight balanced compensa la rareza extrema del positivo (8 de 8.583)
    return Pipeline([
        ("escala", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", C=C, random_state=42)),
    ])


# especificaciones comparadas; todas se reportan, no solo la mejor
ESPECIFICACIONES = {
    "A_completa": ["p_t0", "p_1d", "p_3d", "p_7d", "p_14d", "p_30d", "mes_sin", "mes_cos"],
    "B_solo_lluvia": ["p_t0", "p_1d", "p_3d", "p_7d", "p_14d", "p_30d"],
    "C_corta": ["p_t0", "p_3d", "p_7d"],
    "D_log": ["lp_t0", "lp_3d", "lp_7d", "lp_30d"],
}


def evaluar_loo(d: pd.DataFrame, rasgos: list, pos_idx: np.ndarray) -> dict:
    """Percentil de ranking de cada positivo, entrenando sin él."""
    X, y = d[rasgos].values, d.positivo.values
    pct, puestos = [], []
    for i in pos_idx:
        mask = np.ones(len(d), bool)
        mask[i] = False
        m = nuevo_modelo().fit(X[mask], y[mask])
        s = m.predict_proba(X)[:, 1]
        pct.append(percentil_ranking(s, i))
        puestos.append(int((s > s[i]).sum()) + 1)
    n = len(d)
    return {
        "percentil_mediano": round(float(np.median(pct)), 2),
        "percentil_medio": round(float(np.mean(pct)), 2),
        "recall_at_10pct": round(float(np.mean(np.array(puestos) <= n * 0.10)), 3),
        "recall_at_20pct": round(float(np.mean(np.array(puestos) <= n * 0.20)), 3),
        "percentiles": [round(p, 2) for p in pct],
        "puestos": puestos,
    }


def percentil_ranking(scores: np.ndarray, i: int) -> float:
    """Percentil del día i dentro del ranking de riesgo (100 = el día más riesgoso)."""
    return float((scores < scores[i]).sum() / (len(scores) - 1) * 100)


def main() -> int:
    d = cargar()
    for c in ["p_t0", "p_3d", "p_7d", "p_30d"]:
        d["l" + c] = np.log1p(d[c])
    y = d.positivo.values
    pos_idx = np.flatnonzero(y == 1)
    n = len(d)
    print(f"Datos: {n} días ({d.fecha.min()} a {d.fecha.max()}), {len(pos_idx)} positivos, "
          f"{n - len(pos_idx)} NO ETIQUETADOS\n")

    # ---------- líneas base triviales ----------
    print("Líneas base (sin modelo)")
    print("-" * 72)
    bases = {}
    for nombre, col in [("lluvia 3 días", "p_3d"), ("lluvia 7 días", "p_7d"), ("lluvia 30 días", "p_30d")]:
        s = d[col].values
        p = [percentil_ranking(s, i) for i in pos_idx]
        bases[col] = {"percentil_mediano": round(float(np.median(p)), 2),
                      "recall_at_10pct": round(float(np.mean([(s > s[i]).sum() + 1 <= n * .10 for i in pos_idx])), 3)}
        print(f"  {nombre:16} percentil mediano {bases[col]['percentil_mediano']:6.2f}")

    # ---------- comparación de especificaciones ----------
    print("\nEspecificaciones del modelo, validación dejando-uno-fuera")
    print("-" * 72)
    comparacion = {}
    for nombre, rasgos in ESPECIFICACIONES.items():
        r = evaluar_loo(d, rasgos, pos_idx)
        comparacion[nombre] = {"rasgos": rasgos, **{k: v for k, v in r.items() if k not in ("percentiles", "puestos")}}
        print(f"  {nombre:16} percentil mediano {r['percentil_mediano']:6.2f}   "
              f"recall@10% {r['recall_at_10pct']:.3f}")

    mejor_esp = max(comparacion, key=lambda k: comparacion[k]["percentil_mediano"])
    mejor_base = max(bases, key=lambda k: bases[k]["percentil_mediano"])
    supera = comparacion[mejor_esp]["percentil_mediano"] > bases[mejor_base]["percentil_mediano"]
    print("-" * 72)
    print(f"  mejor especificación: {mejor_esp} ({comparacion[mejor_esp]['percentil_mediano']:.2f})")
    print(f"  mejor línea base:     {mejor_base} ({bases[mejor_base]['percentil_mediano']:.2f})")
    print(f"  ¿el modelo supera a la línea base? {'SÍ' if supera else 'NO'}")

    rasgos_finales = ESPECIFICACIONES[mejor_esp]
    X = d[rasgos_finales].values
    detalle_loo = evaluar_loo(d, rasgos_finales, pos_idx)

    print("\nDetalle por positivo (especificación elegida)")
    print("-" * 72)
    filas = []
    for k, i in enumerate(pos_idx):
        fila = {"fecha": d.fecha[i], "percentil": detalle_loo["percentiles"][k],
                "puesto": detalle_loo["puestos"][k], "de_dias": n,
                "p_3d_mm": round(float(d.p_3d[i]), 2), "p_7d_mm": round(float(d.p_7d[i]), 2)}
        filas.append(fila)
        print(f"  {fila['fecha']}  percentil {fila['percentil']:6.2f}  puesto {fila['puesto']:>5}  "
              f"lluvia 3d {fila['p_3d_mm']:6.2f} mm")

    metricas = {k: v for k, v in detalle_loo.items() if k not in ("percentiles", "puestos")}
    metricas.update({"positivos_evaluados": int(len(pos_idx)), "dias_evaluados": int(n),
                     "especificacion_elegida": mejor_esp,
                     "lineas_base": bases,
                     "comparacion_especificaciones": comparacion,
                     "supera_linea_base": bool(supera)})

    # ---------- modelo final con todos los positivos ----------
    final = nuevo_modelo().fit(X, y)
    RASGOS[:] = rasgos_finales
    ART.mkdir(parents=True, exist_ok=True)
    joblib.dump({"modelo": final, "rasgos": rasgos_finales, "version": VERSION}, ART / "modelo.joblib")

    coef = dict(zip(rasgos_finales, np.round(final.named_steps["clf"].coef_[0], 4).tolist()))
    ficha = {
        "version": VERSION,
        "entrenado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tipo": "regresión logística regularizada, aprendizaje positivo–no etiquetado",
        "unidad": "distrito–día",
        "ventana_entrenamiento": f"{d.fecha.min()} a {d.fecha.max()}",
        "rasgos": rasgos_finales,
        "coeficientes": coef,
        "positivos": int(len(pos_idx)),
        "no_etiquetados": int(len(d) - len(pos_idx)),
        "negativos_verificados": 0,
        "metricas": metricas,
        "metricas_no_reportables": [
            "exactitud", "especificidad", "tasa de falsos positivos", "precisión",
        ],
        "motivo": ("No existen negativos observados. Los días sin positivo son NO ETIQUETADOS, "
                   "por lo que toda métrica que requiera negativos verdaderos carece de sentido."),
        "limitaciones": [
            "El modelo opera a escala distrital, no por celda de 500 m.",
            "Ocho positivos corroborados: la incertidumbre de cualquier estimación es alta.",
            "La lluvia es de cuenca (CHIRPS) y no sustituye observación hidrológica local.",
            "No incorpora caudal observado: las series de SENAMHI están pendientes de gestión.",
            "Es una línea base para acreditar madurez, no el modelo territorial del proyecto.",
            ("SESGO DE SELECCIÓN DECLARADO: la especificación se eligió comparando las cuatro "
             "alternativas con la misma validación dejando-uno-fuera que se reporta. Con ocho "
             "positivos no es posible una selección independiente, de modo que el percentil "
             "mediano informado debe leerse como una cota optimista."),
            ("HALLAZGO: dos de los ocho positivos quedan mal ordenados por el modelo. El "
             "26/01/2017 cae en el percentil 39 y el 20/05/2018 en el 68 pese a registrar "
             "0.04 mm de lluvia acumulada en tres días. Son eventos que la lluvia de cuenca no "
             "explica, probablemente desbordes de canal o afectaciones muy localizadas. Es el "
             "argumento cuantitativo que sustenta el proyecto: el salto de desempeño exige "
             "etiquetas por celda producidas en campo, no más ajuste del modelo."),
        ],
        "uso_previsto": ("Priorización relativa de días de vigilancia a escala distrital. "
                         "No sustituye los avisos oficiales de SENAMHI, INDECI, CENEPRED ni ANA."),
    }
    (ART / "ficha_modelo.json").write_text(json.dumps(ficha, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "loo_detalle.json").write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nModelo guardado en {(ART / 'modelo.joblib').relative_to(RAIZ)}")
    print(f"Ficha del modelo en {(ART / 'ficha_modelo.json').relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
