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

# Static files are collected at build time AND again when the container starts
# (deploy/entrypoint.sh), because some platforms mount an empty volume over
# /app/staticfiles.  DJANGO_DEBUG=False is required so that Django uses the
# hashed manifest storage - with DEBUG on there is no manifest and every
# static file 404s.  No "|| true" here: a broken static build must fail the
# image build instead of shipping a dashboard without CSS or Chart.js.
RUN DJANGO_DEBUG=False python manage.py collectstatic --noinput

# A Windows checkout has no executable bit, so the script would arrive
# without one and the container would refuse to start.
RUN chmod +x /app/deploy/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health/ || exit 1

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["gunicorn", "factory_dashboard.wsgi:application", "-c", "deploy/gunicorn.conf.py"]
