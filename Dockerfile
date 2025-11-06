# syntax=docker/dockerfile:1

FROM node:18-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

ENV PLC_HOST=127.0.0.1 \
    PLC_PORT=44818 \
    PLC_POOL_SIZE=2 \
    PLC_API_TOKEN=

EXPOSE 8000
CMD ["uvicorn", "webapi.main:app", "--host", "0.0.0.0", "--port", "8000"]
