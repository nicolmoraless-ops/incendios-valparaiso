"""Entrena el clasificador de riesgo (BAJO / MEDIO / ALTO / EXTREMO).

IMPORTANTE: el dataset es SINTÉTICO. Las etiquetas se generan con un índice
heurístico inspirado en la regla 30-30-30 usada por CONAF (temperatura > 30 °C,
humedad < 30 %, viento > 30 km/h). Debe reemplazarse por datos históricos
reales (CONAF + estaciones meteorológicas) antes de cualquier uso operativo.
"""
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split

FEATURES = ["temperatura", "humedad", "viento", "dias_sin_lluvia", "ndvi", "pendiente"]
VERSION = "rf-1.0.0"
SALIDA = Path("modelo")


def generar_dataset(n: int = 20000, semilla: int = 42):
    rng = np.random.default_rng(semilla)
    temp = rng.normal(24, 7, n).clip(0, 45)
    hum = rng.normal(55, 18, n).clip(5, 100)
    viento = rng.gamma(2.5, 7, n).clip(0, 90)
    dias = rng.integers(0, 120, n)
    ndvi = rng.uniform(0.1, 0.8, n)
    pend = rng.uniform(0, 35, n)

    indice = (
        0.30 * np.clip((temp - 15) / 20, 0, 1)
        + 0.30 * np.clip((60 - hum) / 50, 0, 1)
        + 0.20 * np.clip(viento / 40, 0, 1)
        + 0.12 * np.clip(dias / 60, 0, 1)
        + 0.04 * np.clip(ndvi / 0.8, 0, 1)
        + 0.04 * np.clip(pend / 30, 0, 1)
        + rng.normal(0, 0.03, n)  # ruido de observación
    )
    nivel = np.select([indice < 0.35, indice < 0.55, indice < 0.72],
                      ["BAJO", "MEDIO", "ALTO"], "EXTREMO").astype("<U8")
    nivel[(temp > 30) & (hum < 30) & (viento > 30)] = "EXTREMO"  # regla 30-30-30

    X = np.column_stack([temp, hum, viento, dias, ndvi, pend])
    return X, nivel


def main():
    X, y = generar_dataset()
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)
    modelo = RandomForestClassifier(n_estimators=150, max_depth=12, min_samples_leaf=3,
                                    class_weight="balanced", n_jobs=-1, random_state=42)
    modelo.fit(X_tr, y_tr)
    pred = modelo.predict(X_te)

    metricas = {
        "version": VERSION,
        "dataset": "sintetico (n=20000, 80/20 estratificado)",
        "accuracy": round(float(accuracy_score(y_te, pred)), 4),
        "f1_macro": round(float(f1_score(y_te, pred, average="macro")), 4),
        "reporte": classification_report(y_te, pred, output_dict=True),
        "importancia_variables": dict(zip(FEATURES, map(lambda v: round(float(v), 4),
                                                         modelo.feature_importances_))),
    }
    SALIDA.mkdir(exist_ok=True)
    joblib.dump({"modelo": modelo, "features": FEATURES, "version": VERSION}, SALIDA / "modelo.joblib",
                compress=3)
    (SALIDA / "metricas.json").write_text(json.dumps(metricas, indent=2, ensure_ascii=False))
    print(f"[train] {VERSION} accuracy={metricas['accuracy']} f1_macro={metricas['f1_macro']}")


if __name__ == "__main__":
    main()
