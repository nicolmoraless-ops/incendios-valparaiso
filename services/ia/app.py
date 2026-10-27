"""Servicio de inferencia IA: clasifica el nivel de riesgo de incendio forestal.

Servicio interno (no expuesto a Internet): exige la cabecera X-Internal-Key.
"""
import hmac
import json
import logging
import os
import time
from pathlib import Path

import joblib
import numpy as np
from fastapi import FastAPI, Header, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

RUTA_MODELO = Path(os.getenv("MODEL_PATH", "modelo/modelo.joblib"))
INTERNAL_KEY = os.environ["INTERNAL_API_KEY"]

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ia")

paquete = joblib.load(RUTA_MODELO)
MODELO, FEATURES, VERSION = paquete["modelo"], paquete["features"], paquete["version"]
METRICAS = json.loads((RUTA_MODELO.parent / "metricas.json").read_text())

INFERENCIAS = Counter("ia_inferencias_total", "Inferencias realizadas", ["nivel"])
DURACION = Histogram("ia_inferencia_duracion_segundos", "Duración de la inferencia",
                     buckets=(0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5))
RECHAZOS = Counter("ia_solicitudes_rechazadas_total", "Solicitudes sin clave interna válida")

app = FastAPI(title="Servicio IA - Riesgo de incendio", version=VERSION)


class Features(BaseModel):
    temperatura: float = Field(ge=-10, le=50)
    humedad: float = Field(ge=0, le=100)
    viento: float = Field(ge=0, le=150)
    dias_sin_lluvia: int = Field(ge=0, le=365)
    ndvi: float = Field(ge=-1, le=1)
    pendiente: float = Field(ge=0, le=90)


@app.get("/health")
def health():
    return {"status": "ok", "modelo": VERSION}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/v1/modelo")
def info_modelo(x_internal_key: str | None = Header(default=None)):
    _verificar(x_internal_key)
    return {"version": VERSION, "features": FEATURES,
            "accuracy": METRICAS["accuracy"], "f1_macro": METRICAS["f1_macro"],
            "importancia_variables": METRICAS["importancia_variables"]}


@app.post("/v1/predict")
def predecir(f: Features, x_internal_key: str | None = Header(default=None)):
    _verificar(x_internal_key)
    inicio = time.perf_counter()
    X = np.array([[getattr(f, c) for c in FEATURES]], dtype=float)
    proba = MODELO.predict_proba(X)[0]
    nivel = str(MODELO.classes_[int(proba.argmax())])
    dur = time.perf_counter() - inicio
    DURACION.observe(dur)
    INFERENCIAS.labels(nivel).inc()
    log.info(json.dumps({"servicio": "ia", "nivel_riesgo": nivel, "duracion_ms": round(dur * 1000, 2)}))
    return {
        "nivel": nivel,
        "probabilidades": {str(c): round(float(p), 3) for c, p in zip(MODELO.classes_, proba)},
        "modelo_version": VERSION,
        "latencia_ms": round(dur * 1000, 2),
    }


def _verificar(clave: str | None):
    if not clave or not hmac.compare_digest(clave, INTERNAL_KEY):
        RECHAZOS.inc()
        raise HTTPException(401, "Clave interna inválida")
