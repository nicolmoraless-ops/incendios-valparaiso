# --- etapa 1: dependencias ---
FROM python:3.12-slim AS deps
WORKDIR /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install/pkgs -r requirements.txt

# --- etapa 2: imagen final mínima, usuario sin privilegios ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 app
COPY --from=deps /install/pkgs /usr/local
WORKDIR /srv
COPY app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=2).status==200 else 1)"
# Un proceso por contenedor: se escala horizontalmente con réplicas (métricas Prometheus consistentes)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
