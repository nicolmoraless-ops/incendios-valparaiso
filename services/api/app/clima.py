"""Obtiene variables meteorológicas reales desde Open-Meteo, con caché en Redis (TTL)."""
import json
import os

import httpx

from .db import redis_cli

URL = "https://api.open-meteo.com/v1/forecast"
TTL = int(os.getenv("CLIMA_CACHE_TTL", "600"))
UMBRAL_LLUVIA_MM = 1.0


def obtener(lat: float, lon: float, cliente: httpx.Client) -> dict:
    clave = f"clima:{lat:.3f}:{lon:.3f}"
    try:
        guardado = redis_cli.get(clave)
    except Exception:  # noqa: BLE001 - si la caché falla se consulta directo
        guardado = None
    if guardado:
        return json.loads(guardado) | {"fuente": "open-meteo (cache)"}

    params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "daily": "precipitation_sum", "past_days": 30, "forecast_days": 1,
        "timezone": "America/Santiago",
    }
    resp = cliente.get(URL, params=params)
    resp.raise_for_status()
    j = resp.json()

    dias = 0  # días consecutivos sin lluvia significativa, sin contar hoy
    for mm in reversed(j["daily"]["precipitation_sum"][:-1]):
        if mm is not None and mm >= UMBRAL_LLUVIA_MM:
            break
        dias += 1

    datos = {
        "temperatura": j["current"]["temperature_2m"],
        "humedad": j["current"]["relative_humidity_2m"],
        "viento": j["current"]["wind_speed_10m"],
        "dias_sin_lluvia": dias,
    }
    try:
        redis_cli.setex(clave, TTL, json.dumps(datos))
    except Exception:  # noqa: BLE001
        pass
    return datos | {"fuente": "open-meteo"}
