# --- etapa 1: entrenamiento reproducible (semilla fija) ---
FROM python:3.12-slim AS entrenamiento
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY train.py .
RUN python train.py

# --- etapa 2: servicio de inferencia (solo modelo + código de serving) ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MODEL_PATH=/srv/modelo/modelo.joblib
RUN useradd --create-home --uid 10001 app
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=entrenamiento /build/modelo ./modelo
COPY app.py .
USER app
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health',timeout=2).status==200 else 1)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
