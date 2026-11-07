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
COPY --from=frontend /frontend/dist ./static

RUN useradd --create-home appuser && mkdir /data && chown appuser /data
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
