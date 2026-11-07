# ---- Base image ----------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=factory_dashboard.settings

WORKDIR /app

# build-essential + libpq-dev are needed to compile psycopg2 on slim images.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Static files are collected at build time; WhiteNoise serves them in the
# container, nginx serves them in production.
RUN python manage.py collectstatic --noinput || true

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health/ || exit 1

CMD ["gunicorn", "factory_dashboard.wsgi:application", "-c", "deploy/gunicorn.conf.py"]
