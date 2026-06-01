"""
FastAPI server — Railway deployment.
Serves Mini App HTML + WebSocket updates.
"""

import asyncio
import logging
import os
import sys

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Ensure parent dir is on path for imports of analyzer_lmb, api_client_lmb, etc.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import config
from railway_app.connection_manager import ConnectionManager
from railway_app.scheduler_async import ciclo_actualizacion, run_initial_analysis, _cache, _build_data

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

app = FastAPI(title="MLB LMB Analytics")
ws_manager = ConnectionManager()

# ── Templates ──────────────────────────────────────────────────────────
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

# ── Startup ────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("=== Railway App iniciando ===")
    # Run initial analysis in background (non-blocking)
    asyncio.create_task(_background_init())
    # Start live update loop immediately
    asyncio.create_task(ciclo_actualizacion(ws_manager))


async def _background_init():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_initial_analysis)
    data = _build_data()
    await ws_manager.broadcast({"type": "full_update", "data": data})
    logger.info("=== Análisis inicial completado ===")


# ── Routes ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    path = os.path.join(TEMPLATES_DIR, "index.html")
    if not os.path.exists(path):
        return HTMLResponse("<h1>Mini App no encontrada</h1>", status_code=404)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(html)


@app.get("/data")
async def get_data():
    """JSON endpoint for polling fallback."""
    data = _build_data()
    return JSONResponse(data)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        # Send current data immediately on connect
        data = _build_data()
        import json as _json
        await ws.send_text(_json.dumps({"type": "full_update", "data": data}, ensure_ascii=False, default=str))
        # Keep connection open, manager handles broadcast
        while True:
            await ws.receive_text()  # just keep alive
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(ws)


@app.get("/privacy.html", response_class=HTMLResponse)
async def privacy():
    path = os.path.join(TEMPLATES_DIR, "privacy.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Privacidad</h1>", status_code=404)

@app.get("/terms.html", response_class=HTMLResponse)
async def terms():
    path = os.path.join(TEMPLATES_DIR, "terms.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Términos</h1>", status_code=404)

@app.get("/health")
async def health():
    return {"status": "ok", "games_cached": len(_cache.get("live_data", {}))}


@app.post("/sync")
async def sync_data(request):
    """Receive estado + CSV data from local bot to keep mini app updated."""
    import json as _json
    try:
        body = await request.json()
    except Exception:
        return {"error": "Invalid JSON"}

    estado = body.get("estado")
    csv_rows = body.get("csv")

    if estado is not None:
        import data_manager as dm
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "partidos_seguimiento.json")
        # Also try local
        local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "partidos_seguimiento.json")
        for p in [local_path, path]:
            try:
                with open(p, "w", encoding="utf-8") as f:
                    _json.dump(estado, f, ensure_ascii=False, indent=2)
                logger.info(f"Sync: estado guardado → {p} ({len(estado)} partidos)")
                break
            except Exception as e:
                logger.warning(f"Sync: no se pudo escribir en {p}: {e}")

    if csv_rows is not None:
        import csv as _csv
        import data_manager as dm
        cols = dm.CSV_COLUMNAS
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "apuestas.csv")
        local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "apuestas.csv")
        for p in [local_path, path]:
            try:
                with open(p, "w", newline="", encoding="utf-8") as f:
                    w = _csv.DictWriter(f, fieldnames=cols)
                    w.writeheader()
                    for row in csv_rows:
                        w.writerow({k: row.get(k, "") for k in cols})
                logger.info(f"Sync: CSV guardado → {p} ({len(csv_rows)} filas)")
                break
            except Exception as e:
                logger.warning(f"Sync: no se pudo escribir en {p}: {e}")

    # Rebuild cache and broadcast
    data = _build_data()
    await ws_manager.broadcast({"type": "full_update", "data": data})

    return {"status": "ok", "estado": len(estado or []), "csv": len(csv_rows or [])}


@app.get("/linescore/{game_pk}")
async def get_linescore(game_pk: int):
    """Linescore detallado de un partido (inning grid + R/H/E + outs + bases)."""
    live_data = _cache.get("live_data", {})
    pk = str(game_pk)
    game_live = live_data.get(pk, {})
    if not game_live:
        return {"error": "Not found", "game_pk": game_pk}
    return {
        "game_pk": game_pk,
        "status": game_live.get("status", ""),
        "is_final": game_live.get("is_final", False),
        "is_live": game_live.get("is_live", False),
        "away_team_name": game_live.get("away_team_name", ""),
        "home_team_name": game_live.get("home_team_name", ""),
        "away_runs": game_live.get("away_runs", 0),
        "home_runs": game_live.get("home_runs", 0),
        "away_hits": game_live.get("away_hits", 0),
        "home_hits": game_live.get("home_hits", 0),
        "away_errors": game_live.get("away_errors", 0),
        "home_errors": game_live.get("home_errors", 0),
        "linescore": game_live.get("linescore", {}),
    }


# ── Static files ───────────────────────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Entry point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
