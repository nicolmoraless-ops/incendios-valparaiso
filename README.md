# Sistema de apoyo a la prevención y clasificación de riesgo de incendios forestales — Región de Valparaíso

Proyecto ITY1102 · Arquitectura de Sistemas de Inteligencia Artificial · EP2

Un usuario autenticado elige una comuna en el mapa; el sistema obtiene el **clima real** (Open-Meteo),
lo combina con variables territoriales (NDVI, pendiente) almacenadas en PostGIS, el **servicio IA**
clasifica el riesgo (BAJO / MEDIO / ALTO / EXTREMO) y, si es ALTO o EXTREMO, un **worker** que consume
eventos genera una alerta. Todo queda observable en **Grafana**.

```
Navegador ──► Nginx (LB least_conn + rate limit) ──► API Gateway ×2 ──► Servicio IA (RandomForest)
                                                      │   │
                                    Open-Meteo ◄──────┘   ├──► PostgreSQL + PostGIS
                                                          └──► Redis (caché + stream eventos.riesgo) ──► Worker de alertas
Prometheus ◄── /metrics de api-1, api-2, ia, worker ──► Grafana (dashboard aprovisionado)
```

## Estructura

| Ruta | Contenido |
|---|---|
| `services/api` | API Gateway FastAPI: JWT, RBAC, orquestación de la consulta, métricas, logs JSON |
| `services/ia` | Entrenamiento (`train.py`, dataset sintético) + servicio de inferencia FastAPI |
| `services/worker` | Consumidor del stream `eventos.riesgo` (patrón Event-Driven) que emite alertas |
| `services/frontend` | Mapa Leaflet (HTML/JS) |
| `nginx/` | Balanceador de carga, cabeceras de seguridad, rate limiting |
| `db/init.sql` | Esquema PostgreSQL/PostGIS y comunas de la región |
| `monitoring/` | Prometheus, reglas de alerta, datasource y dashboard de Grafana |
| `k8s/` | Manifiestos Kubernetes: Deployments, HPA, PDB, probes, Ingress, NetworkPolicy |
| `scripts/` | Generadores de carga (PowerShell y bash) |

## Ejecución (VM o equipo local con Docker)

Requisitos: Docker Engine 24+ con Docker Compose v2, 4 GB de RAM libres, acceso a Internet (imágenes y Open-Meteo).

```bash
cp .env.example .env        # y editar TODAS las contraseñas
docker compose up -d --build
docker compose ps           # todos los servicios "healthy"/"running"
```

| Servicio | URL |
|---|---|
| Frontend + API (vía balanceador) | http://localhost:8080 |
| Grafana (usuario `admin`, clave `GRAFANA_PASSWORD`) | http://localhost:3000 → carpeta *Incendios Valparaíso* |
| Prometheus | http://localhost:9090 |

### Demostración paso a paso (rúbrica de avance práctico)

1. **Consulta real**: abrir http://localhost:8080, entrar como `analista`, elegir *Quilpué* → *Calcular riesgo*.
   Sin variables manuales la API usa clima actual de Open-Meteo (`fuente_clima: open-meteo`).
2. **Por API**:
   ```bash
   TOKEN=$(curl -s -X POST localhost:8080/api/v1/auth/login -d "username=analista&password=$ANALISTA_PASSWORD" | jq -r .access_token)
   curl -s -X POST localhost:8080/api/v1/riesgo -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" -d '{"comuna":"Viña del Mar"}' | jq
   ```
3. **Balanceo**: la respuesta trae `instancia_api` y la cabecera `X-Upstream`; alterna entre `api-1` y `api-2`.
   Failover: `docker compose stop api-1` y repetir la consulta → sigue respondiendo `api-2`.
4. **Event-Driven**: consultar con variables extremas (32 °C, 25 %, 35 km/h, 40 días) → `docker compose logs worker`
   muestra `alerta.emitida`; como `admin` aparece en el panel *Alertas*.
5. **Monitoreo**: `./scripts/generar-carga.ps1 -Clave <ANALISTA_PASSWORD>` y observar en Grafana RPS por réplica,
   latencia p50/p95/p99, códigos 401/403, latencia de inferencia, CPU y RAM.
6. **Seguridad** (controles demostrables):
   - Sin token → `401`; `analista` pidiendo `/api/v1/alertas` → `403` (RBAC).
   - El servicio IA rechaza llamadas sin `X-Internal-Key` (`401`) y no publica puerto al host.
   - Contraseñas con bcrypt; secretos solo en `.env` / Kubernetes Secret (ignorados por git).
   - Rate limiting en Nginx (`429`) y cabeceras CSP / X-Frame-Options / nosniff.
   - Contenedores con usuario no root.

## Kubernetes (minikube / kind)

```bash
for s in api ia worker frontend; do docker build -t incendios/$s:1.0.0 services/$s; done
minikube image load incendios/api:1.0.0 incendios/ia:1.0.0 incendios/worker:1.0.0 incendios/frontend:1.0.0
minikube addons enable ingress && minikube addons enable metrics-server
kubectl apply -f k8s/00-base.yaml
cp k8s/02-secrets.example.yaml k8s/02-secrets.yaml   # editar valores
kubectl apply -f k8s/02-secrets.yaml
kubectl create configmap db-init --from-file=db/init.sql -n incendios
kubectl apply -f k8s/10-datos.yaml -f k8s/20-servicios.yaml -f k8s/30-ingress-red.yaml
kubectl get pods,hpa -n incendios
```

## Modelo de IA

- `RandomForestClassifier` (150 árboles, profundidad 12), variables: temperatura, humedad, viento,
  días sin lluvia, NDVI y pendiente. Se entrena durante el `docker build` con semilla fija (reproducible)
  y sus métricas quedan en `modelo/metricas.json` dentro de la imagen (`GET /v1/modelo`).
- **Limitación declarada**: el dataset es **sintético**, etiquetado con un índice heurístico basado en la
  regla 30-30-30 de CONAF. Las métricas reflejan la coherencia con esa heurística, no precisión real
  en terreno. Próximo hito: reentrenar con registros históricos de CONAF y estaciones de la DMC.
- NDVI y pendiente por comuna son valores de referencia **estimados**.

## Estado del avance

| Implementado y demostrable | Pendiente / solo diseñado |
|---|---|
| Flujo completo login → clima real → inferencia → PostGIS → evento → alerta | Datos históricos reales para el modelo |
| Docker multi-stage, 2 réplicas API detrás de Nginx `least_conn` con failover | Despliegue en AWS (EKS/RDS/ElastiCache/ALB) — manifiestos y costos listos |
| Prometheus + Grafana con dashboard y reglas de alerta | Notificación real (SNS/correo); hoy se registra y se loguea |
| JWT + RBAC + clave interna + rate limiting + bcrypt + secretos fuera del código | TLS de extremo a extremo (en AWS con ACM en el ALB) |
| Manifiestos Kubernetes (HPA, PDB, probes, NetworkPolicy) | Pruebas de carga formales (k6/Locust) |
