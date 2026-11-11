# Etapa 1: build do frontend (React + Vite)
FROM node:24-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Etapa 2: API (FastAPI) servindo também o frontend estático, em um único container
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/financas.db \
    UPLOAD_DIR=/data/uploads
WORKDIR /app

# Bibliotecas de sistema exigidas pelo OpenCV (leitura de fotos de cupons).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY --from=frontend /frontend/dist ./static

# /data/uploads precisa existir na imagem já com o dono certo: um volume novo montado ali copia
# essa permissão. Sem isso, o Docker cria a pasta como root e o envio de notas falha.
RUN useradd --create-home appuser && mkdir -p /data/uploads && chown -R appuser /data
USER appuser

EXPOSE 8000
# A imagem slim não tem curl: o próprio Python confere se a API responde.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=8)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
