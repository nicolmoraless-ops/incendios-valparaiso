#!/usr/bin/env bash
# Genera tráfico real contra el sistema.  Uso: CLAVE=<ANALISTA_PASSWORD> ./scripts/generar-carga.sh 200
set -euo pipefail
BASE=${BASE:-http://localhost:8080}
N=${1:-200}
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login" -d "username=analista&password=${CLAVE:?defina CLAVE}" \
  | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
COMUNAS=("Valparaíso" "Viña del Mar" "Quilpué" "Villa Alemana" "Concón" "Quillota" "Limache" "Casablanca" "San Antonio" "Los Andes")
for i in $(seq 1 "$N"); do
  C=${COMUNAS[$RANDOM % ${#COMUNAS[@]}]}
  BODY="{\"comuna\":\"$C\",\"variables\":{\"temperatura\":$((12 + RANDOM % 26)),\"humedad\":$((10 + RANDOM % 80)),\"viento\":$((RANDOM % 60)),\"dias_sin_lluvia\":$((RANDOM % 90))}}"
  curl -s -o /dev/null -w "%{http_code} " -X POST "$BASE/api/v1/riesgo" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$BODY"
done
echo
for _ in $(seq 1 10); do curl -s -o /dev/null "$BASE/api/v1/alertas" -H "Authorization: Bearer $TOKEN"; done  # 403
for _ in $(seq 1 10); do curl -s -o /dev/null "$BASE/api/v1/consultas"; done                                  # 401
echo "Listo. Revise Grafana en http://localhost:3000"
