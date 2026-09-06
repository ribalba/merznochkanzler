#!/usr/bin/env python3
"""
Liefert site/ aus und baut die Seite einmal täglich neu.

Ein Prozess, keine Abhängigkeiten außerhalb der Standardbibliothek und kein cron:
Der Build läuft in einem Nebenverzeichnis und wird erst nach Erfolg eingeblendet.
Schlägt er fehl, bleibt die zuletzt erfolgreiche Fassung online und es wird nach
RETRY_MINUTES erneut versucht.

Konfiguration über Umgebungsvariablen:
    PORT            Port (Standard 8080)
    REBUILD_AT      Uhrzeit des täglichen Builds als HH:MM Ortszeit (Standard 04:15)
    RETRY_MINUTES   Wartezeit nach einem fehlgeschlagenen Build (Standard 30)
    BUILD_ON_START  "0" überspringt den Build beim Start (Standard 1)
    SITE_DIR        Ausgabeverzeichnis (Standard ./site)
"""
import datetime as dt
import http.server
import json
import os
import pathlib
import shutil
import signal
import socketserver
import subprocess
import sys
import threading

HERE = pathlib.Path(__file__).parent.resolve()
SITE_DIR = pathlib.Path(os.environ.get("SITE_DIR", HERE / "site")).resolve()
STAGING_DIR = SITE_DIR / ".build"   # im selben Dateisystem, sonst kein os.replace
PORT = int(os.environ.get("PORT", "8080"))
RETRY_MINUTES = int(os.environ.get("RETRY_MINUTES", "30"))
BUILD_ON_START = os.environ.get("BUILD_ON_START", "1") != "0"
BUILD_TIMEOUT = 300

stop = threading.Event()
state = {"last_success": None, "last_attempt": None, "last_error": None,
         "builds_ok": 0, "builds_failed": 0}


def log(msg):
    print(f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


def rebuild_at():
    raw = os.environ.get("REBUILD_AT", "04:15")
    try:
        h, m = (int(x) for x in raw.split(":", 1))
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except ValueError:
        pass
    log(f"REBUILD_AT={raw!r} ist ungültig, benutze 04:15")
    return 4, 15


def build():
    """Baut nach STAGING_DIR und übernimmt die Dateien erst bei Erfolg."""
    state["last_attempt"] = dt.datetime.now().isoformat(timespec="seconds")
    shutil.rmtree(STAGING_DIR, ignore_errors=True)
    try:
        proc = subprocess.run(
            [sys.executable, str(HERE / "build.py"), "--out", str(STAGING_DIR)],
            cwd=HERE, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        state["last_error"] = f"Build nach {BUILD_TIMEOUT}s abgebrochen"
        state["builds_failed"] += 1
        log("Build: Zeitüberschreitung")
        return False
    if proc.returncode != 0:
        state["last_error"] = (proc.stderr or proc.stdout).strip()[-500:]
        state["builds_failed"] += 1
        log(f"Build fehlgeschlagen (Code {proc.returncode}): {state['last_error']}")
        return False

    try:
        for src in sorted(STAGING_DIR.iterdir()):
            os.replace(src, SITE_DIR / src.name)   # gleiches Dateisystem, daher atomar
    except OSError as e:
        state["last_error"] = f"Übernahme fehlgeschlagen: {e}"
        state["builds_failed"] += 1
        log(state["last_error"])
        return False
    finally:
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
    state["last_success"] = dt.datetime.now().isoformat(timespec="seconds")
    state["last_error"] = None
    state["builds_ok"] += 1
    log(f"Build ok: {proc.stdout.strip()}")
    return True


def scheduler():
    """Wartet bis zur nächsten Bauzeit, nach einem Fehlschlag kürzer."""
    while not stop.is_set():
        h, m = rebuild_at()
        now = dt.datetime.now()
        nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if nxt <= now:
            nxt += dt.timedelta(days=1)
        if state["last_error"] is not None:
            nxt = min(nxt, now + dt.timedelta(minutes=RETRY_MINUTES))
        log(f"Nächster Build: {nxt.isoformat(timespec='seconds')}")
        if stop.wait((nxt - dt.datetime.now()).total_seconds()):
            return
        build()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SITE_DIR), **kw)

    def do_GET(self):
        path = self.path.split("?")[0]
        if any(part.startswith(".") for part in path.split("/")):
            self.send_error(404)
            return
        if path == "/healthz":
            healthy = (state["last_success"] is not None
                       or (SITE_DIR / "index.html").exists())
            body = json.dumps({"status": "ok" if healthy else "no build yet", **state},
                              ensure_ascii=False).encode()
            self.send_response(200 if healthy else 503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        # Die Seite ändert sich einmal am Tag; kurze Frist statt Dauer-Cache.
        self.send_header("Cache-Control", "public, max-age=900")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def log_message(self, fmt, *args):
        log(f"{self.address_string()} {fmt % args}")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    with Server(("", PORT), Handler) as httpd:
        # Erst lauschen, dann bauen: /healthz ist sofort erreichbar und meldet,
        # dass noch kein Build vorliegt, statt die Verbindung zu verweigern.
        log(f"Lauscht auf Port {PORT}, Verzeichnis {SITE_DIR}")
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.5},
                         daemon=True).start()

        if BUILD_ON_START:
            log("Erster Build läuft…")
            if not build() and not (SITE_DIR / "index.html").exists():
                log("Kein Build und keine vorhandene Seite – es wird 404 ausgeliefert.")
        threading.Thread(target=scheduler, daemon=True).start()

        stop.wait()
        log("Beende…")
        httpd.shutdown()


if __name__ == "__main__":
    main()
