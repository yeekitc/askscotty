FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]

# entrypoint.sh ends in `exec "$@"`, so without a CMD the container would run
# migrations and then exit silently. docker-compose overrides this with
# runserver for hot reload; this default makes the image runnable on its own.
#
# gthread, not sync: /api/ask/stream/ holds its worker for the whole life of the
# stream, so N sync workers cap the deploy at N concurrent questions.
#
# --timeout 300 because gunicorn's default is 30s and a sync-family worker does
# not heartbeat mid-request — every multi-hop answer slower than that would have
# its worker killed and the stream cut. Answers run 30-120s; the app's own
# ceiling (lib/api.ts) is 120s.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--worker-class", "gthread", \
     "--workers", "2", \
     "--threads", "8", \
     "--timeout", "300", \
     "--access-logfile", "-"]
