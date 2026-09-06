# Ein Prozess: serve.py baut die Seite und liefert sie aus (siehe serve.py).
FROM python:3.13-alpine

# tzdata, damit REBUILD_AT eine Ortszeit ist und nicht UTC.
RUN apk add --no-cache tzdata

ENV TZ=Europe/Berlin \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    REBUILD_AT=04:15 \
    SITE_DIR=/app/site

WORKDIR /app
COPY build.py serve.py style.css template.html impressum.html ./

RUN adduser -D -u 10001 app \
 && mkdir -p /app/site \
 && chown -R app:app /app
USER app

EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=300s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

CMD ["python3", "serve.py"]
