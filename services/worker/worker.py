"""Worker de alertas (patrón Event-Driven).

Consume el stream Redis `eventos.riesgo` mediante un consumer group; cuando el
nivel es ALTO o EXTREMO registra una alerta y emite la notificación (simulada
por log; en producción: SNS/correo a brigadas y municipios).
"""
import json
import logging
import os
import socket
import time

import psycopg
import redis
from prometheus_client import Counter, start_http_server

STREAM, GRUPO = "eventos.riesgo", "alertas"
CONSUMIDOR = socket.gethostname()
NIVELES_ALERTA = {"ALTO", "EXTREMO"}

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("worker")

EVENTOS = Counter("eventos_procesados_total", "Eventos consumidos", ["nivel"])
ALERTAS = Counter("alertas_generadas_total", "Alertas generadas", ["nivel", "comuna"])
ERRORES = Counter("eventos_con_error_total", "Eventos que fallaron al procesarse")


def conectar_redis():
    r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        r.xgroup_create(STREAM, GRUPO, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise
    return r


def procesar(conn, ev: dict):
    EVENTOS.labels(ev["nivel"]).inc()
    if ev["nivel"] not in NIVELES_ALERTA:
        return
    mensaje = (f"Riesgo {ev['nivel']} de incendio forestal en {ev['comuna']} "
               f"(p={max(ev['probabilidades'].values()):.2f}). Activar protocolo preventivo.")
    conn.execute(
        "INSERT INTO alertas (consulta_id, comuna, nivel, mensaje) VALUES (%s, %s, %s, %s)",
        (ev["consulta_id"], ev["comuna"], ev["nivel"], mensaje),
    )
    ALERTAS.labels(ev["nivel"], ev["comuna"]).inc()
    log.info(json.dumps({"servicio": "worker", "evento": "alerta.emitida", "comuna": ev["comuna"],
                         "nivel": ev["nivel"], "consulta_id": ev["consulta_id"]}))


def main():
    start_http_server(int(os.getenv("METRICS_PORT", "9101")))
    r = conectar_redis()
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    log.info(json.dumps({"servicio": "worker", "msg": f"escuchando {STREAM} como {CONSUMIDOR}"}))
    # Primero reprocesa pendientes propios (at-least-once), luego mensajes nuevos.
    ultimo_id = "0"
    while True:
        try:
            resp = r.xreadgroup(GRUPO, CONSUMIDOR, {STREAM: ultimo_id}, count=20, block=5000)
            if ultimo_id == "0" and (not resp or not resp[0][1]):
                ultimo_id = ">"
                continue
            for _stream, entradas in resp or []:
                for mid, campos in entradas:
                    try:
                        procesar(conn, json.loads(campos["datos"]))
                        r.xack(STREAM, GRUPO, mid)
                    except psycopg.OperationalError:
                        raise  # sin ack: el mensaje queda pendiente y se reprocesa al reconectar
                    except Exception as e:  # noqa: BLE001
                        ERRORES.inc()
                        log.error(json.dumps({"servicio": "worker", "error": str(e), "id": mid}))
        except (redis.ConnectionError, psycopg.OperationalError) as e:
            log.error(json.dumps({"servicio": "worker", "error": f"reconectando: {e}"}))
            time.sleep(3)
            try:
                r = conectar_redis()
                if conn.closed or conn.broken:
                    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
                ultimo_id = "0"
            except Exception:  # noqa: BLE001 - se reintenta en la siguiente vuelta
                pass


if __name__ == "__main__":
    main()
