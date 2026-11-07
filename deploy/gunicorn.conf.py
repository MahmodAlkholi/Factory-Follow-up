"""Gunicorn configuration for the Factory Follow-up Dashboard.

    gunicorn factory_dashboard.wsgi:application -c deploy/gunicorn.conf.py
"""

import multiprocessing
import os

# Cloud Run, Render, Heroku, HF Spaces and friends tell the process which port
# to listen on through $PORT; fall back to 8000 for a plain local run.
bind = os.environ.get("GUNICORN_BIND") or "0.0.0.0:%s" % os.environ.get("PORT", "8000")

# 2 workers + 1 per extra core, but never more than 8: the dashboard is
# I/O bound (Postgres + Redis), not CPU bound.
workers = int(os.environ.get("GUNICORN_WORKERS", min(multiprocessing.cpu_count() * 2 + 1, 8)))
threads = int(os.environ.get("GUNICORN_THREADS", 2))
worker_class = "gthread"

timeout = int(os.environ.get("GUNICORN_TIMEOUT", 120))
graceful_timeout = 30
keepalive = 5

# Recycle workers so a memory leak in a long running dashboard can never
# take the whole service down.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", 1000))
max_requests_jitter = 100

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sus "%(f)s" "%(a)s"'

proc_name = "factory_dashboard"
forwarded_allow_ips = "*"
