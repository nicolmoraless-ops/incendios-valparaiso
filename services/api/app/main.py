"""API Gateway del sistema de riesgo de incendios forestales - Región de Valparaíso.

Responsabilidades: autenticación/autorización, orquestación de la consulta
(clima -> servicio IA -> persistencia -> evento), métricas y logs estructurados.
"""
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from . import auth, clima, db

INSTANCIA = os.getenv("INSTANCIA", os.getenv("HOSTNAME", "api"))
IA_URL = os.getenv("IA_URL", "http://ia:8001")
INTERNAL_KEY = os.environ["INTERNAL_API_KEY"]
STREAM = "eventos.riesgo"
RUTAS_CONOCIDAS = (
    "/api/v1/riesgo", "/api/v1/auth/login", "/api/v1/comunas",
    "/api/v1/consultas", "/api/v1/alertas", "/api/v1/health", "/health", "/ready",
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("api")

REQS = Counter("http_requests_total", "Solicitudes HTTP", ["ruta", "metodo", "codigo"])
LAT = Histogram(
    "http_request_duration_seconds", "Latencia HTTP", ["ruta"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
NIVELES = Counter("riesgo_clasificaciones_total", "Clasificaciones por nivel", ["nivel"])
FALLOS_IA = Counter("ia_llamadas_fallidas_total", "Llamadas fallidas al servicio IA")

http = httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0))


@asynccontextmanager
async def lifespan(_app):
    db.init_pool()
    auth.seed_usuarios()
    yield
    http.close()
    db.close_pool()


app = FastAPI(title="API Riesgo Incendios Valparaíso", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def metricas_y_logs(request: Request, call_next):
    inicio = time.perf_counter()
    rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    ruta = request.url.path if request.url.path in RUTAS_CONOCIDAS else "otra"
    codigo = 500
    try:
        response = await call_next(request)
        codigo = response.status_code
        response.headers["X-Request-ID"] = rid
        response.headers["X-Instancia"] = INSTANCIA
        return response
    finally:
        dur = time.perf_counter() - inicio
        if request.url.path != "/metrics":
            REQS.labels(ruta, request.method, str(codigo)).inc()
            LAT.labels(ruta).observe(dur)
        log.info(json.dumps({
            "nivel": "INFO", "servicio": "api", "instancia": INSTANCIA, "request_id": rid,
            "metodo": request.method, "ruta": request.url.path, "codigo": codigo,
            "duracion_ms": round(dur * 1000, 1),
        }))


# ---------- Salud y métricas ----------
@app.get("/health")
@app.get("/api/v1/health")
def health():
    """Liveness: el proceso responde."""
    return {"status": "ok", "instancia": INSTANCIA}


@app.get("/ready")
def ready():
    """Readiness: dependencias críticas disponibles (BD y Redis)."""
    try:
        with db.conn() as c:
            c.execute("SELECT 1")
        db.redis_cli.ping()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"No listo: {type(e).__name__}")
    return {"status": "ready", "instancia": INSTANCIA}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------- Autenticación ----------
@app.post("/api/v1/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    usuario = auth.autenticar(form.username, form.password)
    if not usuario:
        raise HTTPException(401, "Credenciales inválidas", headers={"WWW-Authenticate": "Bearer"})
    return {
        "access_token": auth.crear_token(usuario["usuario"], usuario["rol"]),
        "token_type": "bearer", "rol": usuario["rol"], "expira_min": auth.EXP_MIN,
    }


# ---------- Dominio ----------
class Variables(BaseModel):
    temperatura: float = Field(ge=-10, le=50, description="°C")
    humedad: float = Field(ge=0, le=100, description="% humedad relativa")
    viento: float = Field(ge=0, le=150, description="km/h")
    dias_sin_lluvia: int = Field(ge=0, le=365)


class SolicitudRiesgo(BaseModel):
    comuna: str = Field(min_length=2, max_length=60)
    variables: Variables | None = Field(
        default=None, description="Si se omite, se obtienen en tiempo real desde Open-Meteo")


@app.get("/api/v1/comunas")
def listar_comunas(_u=Depends(auth.usuario_actual)):
    with db.conn() as c:
        return c.execute("SELECT id, nombre, lat, lon, ndvi, pendiente FROM comunas ORDER BY nombre").fetchall()


@app.post("/api/v1/riesgo")
def calcular_riesgo(sol: SolicitudRiesgo, request: Request,
                    u=Depends(auth.requiere_rol("admin", "analista"))):
    with db.conn() as c:
        com = c.execute(
            "SELECT id, nombre, lat, lon, ndvi, pendiente FROM comunas WHERE lower(nombre) = lower(%s)",
            (sol.comuna,),
        ).fetchone()
    if not com:
        raise HTTPException(404, "Comuna no registrada")

    if sol.variables:
        meteo = sol.variables.model_dump() | {"fuente": "manual"}
    else:
        try:
            meteo = clima.obtener(com["lat"], com["lon"], http)
        except httpx.HTTPError:
            raise HTTPException(503, "Fuente meteorológica no disponible; envíe 'variables' manualmente")

    features = {k: meteo[k] for k in ("temperatura", "humedad", "viento", "dias_sin_lluvia")}
    features |= {"ndvi": com["ndvi"], "pendiente": com["pendiente"]}

    try:
        resp = http.post(f"{IA_URL}/v1/predict", json=features,
                         headers={"X-Internal-Key": INTERNAL_KEY,
                                  "X-Request-ID": request.headers.get("X-Request-ID", "")})
        resp.raise_for_status()
    except httpx.HTTPError:
        FALLOS_IA.inc()
        raise HTTPException(502, "Servicio IA no disponible")
    pred = resp.json()

    with db.conn() as c:
        fila = c.execute(
            """INSERT INTO consultas (comuna_id, usuario, variables, nivel, probabilidades, modelo_version, geom)
               VALUES (%s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
               RETURNING id, creado_en""",
            (com["id"], u["sub"], Jsonb(features), pred["nivel"], Jsonb(pred["probabilidades"]),
             pred["modelo_version"], com["lon"], com["lat"]),
        ).fetchone()

    NIVELES.labels(pred["nivel"]).inc()
    evento = {
        "tipo": "riesgo.calculado", "consulta_id": fila["id"], "comuna": com["nombre"],
        "nivel": pred["nivel"], "probabilidades": pred["probabilidades"],
        "creado_en": fila["creado_en"].isoformat(),
    }
    try:  # el evento es asíncrono: si Redis falla, la consulta igual se responde
        db.redis_cli.xadd(STREAM, {"datos": json.dumps(evento)}, maxlen=10000, approximate=True)
    except Exception as e:  # noqa: BLE001
        log.warning(json.dumps({"nivel": "WARN", "msg": "no se publicó evento", "error": str(e)}))

    return {
        "consulta_id": fila["id"], "comuna": com["nombre"], "nivel": pred["nivel"],
        "probabilidades": pred["probabilidades"], "variables": features,
        "fuente_clima": meteo["fuente"], "modelo_version": pred["modelo_version"],
        "instancia_api": INSTANCIA,
    }


@app.get("/api/v1/consultas")
def historial(limite: int = 20, _u=Depends(auth.usuario_actual)):
    limite = max(1, min(limite, 100))
    with db.conn() as c:
        return c.execute(
            """SELECT q.id, co.nombre AS comuna, q.nivel, q.probabilidades, q.usuario, q.creado_en
               FROM consultas q JOIN comunas co ON co.id = q.comuna_id
               ORDER BY q.creado_en DESC LIMIT %s""", (limite,)).fetchall()


@app.get("/api/v1/alertas")
def alertas(limite: int = 20, _u=Depends(auth.requiere_rol("admin"))):
    limite = max(1, min(limite, 100))
    with db.conn() as c:
        return c.execute(
            "SELECT id, consulta_id, comuna, nivel, mensaje, creado_en FROM alertas ORDER BY creado_en DESC LIMIT %s",
            (limite,)).fetchall()
