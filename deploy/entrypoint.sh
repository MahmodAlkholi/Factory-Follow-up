#!/bin/sh
# Container entrypoint: prepare the app, then hand over to the real command.
#
#   migrate      - apply the database migrations
#   collectstatic- rebuild the static files (some platforms mount an empty
#                  volume over /app/staticfiles, so the build-time copy is
#                  not enough)
#
# Both steps must succeed: a container that starts with a broken database or
# without static files looks alive but serves nothing useful.
#
# The worker and the beat scheduler do not need either step, so the compose
# file turns them off for those two services (RUN_MIGRATE=0 RUN_COLLECTSTATIC=0)
# and the migration is done once, by the web container.
set -e

if [ "${RUN_MIGRATE:-1}" = "1" ]; then
    python manage.py migrate --noinput
fi

if [ "${RUN_COLLECTSTATIC:-1}" = "1" ]; then
    python manage.py collectstatic --noinput
fi

exec "$@"
