import asyncio
import json
import logging
import os
import sys
from datetime import datetime, date, timedelta, timezone

import httpx
import pytz

# Ensure parent dir is on path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import data_manager as dm
from analyzer_lmb import analizar_lmb_dia

logger = logging.getLogger(__name__)

MT_TZ = pytz.timezone(config.TIMEZONE)

# ── In-memory cache ─────────────────────────────────────────────────────
_cache: dict = {
    "games": [],
    "stats": {},
    "stats_mlb": {},
    "stats_lmb": {},
    "fecha": "",
    "proxima_actualizacion": "",
    "proxima_actualizacion_lmb": "",
    "live_data": {},   # game_pk -> {inning, outs, away_runs, home_runs, ...}
    "dias": [],
}


def _build_data() -> dict:
    """Construye el dict de datos para WebSocket/Mini App."""
    from datetime import datetime as _dt
    hoy = _dt.now()
    ayer = hoy - timedelta(days=1)
    anteayer = hoy - timedelta(days=2)
    fechas = {hoy.strftime("%Y-%m-%d"), ayer.strftime("%Y-%m-%d"), anteayer.strftime("%Y-%m-%d")}

    estado = dm.cargar_estado()
    games = []
    seen = set()

    def norm(n):
        return n.strip().lower()

    def make_key(fecha, away, home):
        return (fecha, norm(away), norm(home))

    stats = dm.obtener_estadisticas()
    stats_mlb = dm.obtener_estadisticas(liga="MLB")
    stats_lmb = dm.obtener_estadisticas(liga="LMB")

    p_min = config.PROB_MINIMA_ANALISIS
    e_min = config.EDGE_MINIMO

    for sg in estado:
        favorito = sg.get("favorito", "")
        away = sg.get("away_team", "")
        home = sg.get("home_team", "")
        fecha_sg = sg.get("game_date", "")[:10]
        if fecha_sg not in fechas:
            continue
        key = make_key(fecha_sg, away, home)
        if key in seen:
            continue
        seen.add(key)

        prob = sg.get("prob_favorito", 0) or 0
        mercado = sg.get("odds_mercado")
        edge = round(prob - mercado, 2) if mercado else None
        if prob >= p_min and edge is not None and edge >= e_min:
            label = "🎯"
        elif prob >= p_min:
            label = "📊"
        else:
            label = "📋"

        pk = sg.get("game_pk", 0)
        live = _cache.get("live_data", {}).get(str(pk), {})

        if live.get("is_final"):
            emoji = "✅" if sg.get("resultado") == "acertado" else "❌"
            state = "Final"
            s_fav = str(live.get("home_runs", "")) if favorito and (norm(favorito) in norm(home)) else str(live.get("away_runs", ""))
            s_opp = str(live.get("away_runs", "")) if favorito and (norm(favorito) in norm(home)) else str(live.get("home_runs", ""))
            result = "win" if sg.get("resultado") == "acertado" else "loss"
        elif live.get("is_live"):
            emoji = "🔴"
            state = live.get("display_inning", live.get("inning_state", "En Vivo"))
            s_fav = str(live.get("home_runs", "")) if favorito and (norm(favorito) in norm(home)) else str(live.get("away_runs", ""))
            s_opp = str(live.get("away_runs", "")) if favorito and (norm(favorito) in norm(home)) else str(live.get("home_runs", ""))
            result = "live"
        else:
            emoji = "⏳"
            state = "Pend."
            s_fav, s_opp = "", ""
            result = "pending"

        _fav_in_home = favorito and (norm(favorito) in norm(home) or norm(home) in norm(favorito))
        fav = home if _fav_in_home else away
        opp = away if _fav_in_home else home
        if not s_fav and not s_opp:
            s_fav, s_opp = "", ""

        liga = sg.get("liga", "MLB")
        games.append({
            "liga": liga,
            "game_date": fecha_sg,
            "status_emoji": emoji,
            "fav_team": fav,
            "opp_team": opp,
            "score_fav": s_fav,
            "score_opp": s_opp,
            "state": state,
            "result": result,
            "label": label,
            "senal": sg.get("senal_moneyline", "NO APOSTAR"),
            "certidumbre": sg.get("nivel_certidumbre", ""),
            "game_pk": pk,
        })

    games.sort(key=lambda x: (x.get("game_date", ""), {"🎯": 0, "📊": 1, "📋": 2}.get(x.get("label", ""), 3)))

    dias_set = set()
    for g in games:
        d = g.get("game_date", "")
        if d:
            dias_set.add(d)
    dias_disponibles = sorted(dias_set, reverse=True)

    ahora_str = _dt.now().strftime("%d/%m/%Y %H:%M")
    prox = getattr(config, "HORA_ANALISIS_MANANA", "08:00")
    prox_lmb = getattr(config, "LMB_HORA_MANANA", "10:00")

    def bs(s):
        return {
            "total": s["total"], "acertados": s["acertados"], "fallidos": s["fallidos"],
            "win_rate": s["win_rate"],
            "alta_total": s["alta_total"], "alta_acertados": s["alta_acertados"], "alta_fallidos": s["alta_fallidos"], "alta_win_rate": s["alta_win_rate"],
            "media_total": s["media_total"], "media_acertados": s["media_acertados"], "media_fallidos": s["media_fallidos"], "media_win_rate": s["media_win_rate"],
            "baja_total": s["baja_total"], "baja_acertados": s["baja_acertados"], "baja_fallidos": s["baja_fallidos"], "baja_win_rate": s["baja_win_rate"],
            "valor_ok": s["valor_ok"], "valor_total": s["valor_total"], "valor_rate": s["valor_rate"],
        }

    return {
        "fecha": ahora_str,
        "proxima_actualizacion": prox,
        "proxima_actualizacion_lmb": prox_lmb,
        "dias": dias_disponibles,
        "games": games,
        "bot_username": config.TELEGRAM_BOT_USERNAME,
        "autorizados": _cargar_suscriptores(),
        "stats": bs(stats),
        "stats_mlb": bs(stats_mlb),
        "stats_lmb": bs(stats_lmb),
    }


def _cargar_suscriptores() -> list[int]:
    # Try local first, then parent dir
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "suscriptores.json"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "suscriptores.json"),
    ]
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            suscripciones = data.get("suscripciones", {})
            admin = data.get("admin_id")
            hoy = date.today().isoformat()
            validos = []
            for uid_str, expira in suscripciones.items():
                uid = int(uid_str)
                if expira is None or expira >= hoy:
                    validos.append(uid)
            if admin and admin not in validos:
                validos.append(admin)
            return validos
        except Exception:
            continue
    return []


async def fetch_live_data() -> dict:
    """Fetch live scores for all LMB and MLB games from StatsAPI."""
    live = {}
    today = date.today()
    date_str = today.strftime("%m/%d/%Y")

    async with httpx.AsyncClient(timeout=15) as client:
        # MLB sportId=1
        try:
            r = await client.get(
                "https://statsapi.mlb.com/api/v1/schedule",
                params={"sportId": 1, "date": date_str, "hydrate": "linescore"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 200:
                for d in r.json().get("dates", []):
                    for g in d.get("games", []):
                        pk = str(g.get("gamePk"))
                        state = g.get("status", {}).get("detailedState", "")
                        ls = g.get("linescore", {})
                        teams = ls.get("teams", {}) if ls else {}
                        inning = ls.get("currentInning", "") if ls else ""
                        inning_state = ls.get("inningState", "") if ls else ""
                        is_final = state in ("Final", "Game Over", "Completed Early")
                        is_live = state in ("In Progress", "Live", "Delayed") or (
                            not is_final and state not in ("Scheduled", "Pre-Game", "Warmup", "")
                        )
                        display_inning = f"{inning_state} {inning}" if inning_state and inning else inning_state or inning or ""
                        # Full linescore for scoreboard widget
                        innings_data = g.get("linescore", {}).get("innings", [])
                        ins = []
                        for inn in innings_data:
                            ins.append({
                                "num": inn.get("num", 0),
                                "away_runs": _safe_int(inn.get("away", {}).get("runs")),
                                "home_runs": _safe_int(inn.get("home", {}).get("runs")),
                                "away_hits": _safe_int(inn.get("away", {}).get("hits")),
                                "home_hits": _safe_int(inn.get("home", {}).get("hits")),
                                "away_errors": _safe_int(inn.get("away", {}).get("errors")),
                                "home_errors": _safe_int(inn.get("home", {}).get("errors")),
                            })
                        ls_detail = g.get("linescore", {})
                        bases_raw = g.get("linescore", {}).get("bases", {}) or g.get("bases", {})
                        away_team_obj = g.get("teams", {}).get("away", {}).get("team", {})
                        home_team_obj = g.get("teams", {}).get("home", {}).get("team", {})
                        live[pk] = {
                            "status": state,
                            "is_final": is_final,
                            "is_live": is_live,
                            "inning": inning or "",
                            "inning_state": inning_state or "",
                            "display_inning": display_inning,
                            "away_runs": _safe_int(teams.get("away", {}).get("runs")),
                            "home_runs": _safe_int(teams.get("home", {}).get("runs")),
                            "away_hits": _safe_int(teams.get("away", {}).get("hits")),
                            "home_hits": _safe_int(teams.get("home", {}).get("hits")),
                            "away_errors": _safe_int(teams.get("away", {}).get("errors")),
                            "home_errors": _safe_int(teams.get("home", {}).get("errors")),
                            "away_team_name": away_team_obj.get("name", ""),
                            "home_team_name": home_team_obj.get("name", ""),
                            "linescore": {
                                "innings": ins,
                                "outs": _safe_int(ls_detail.get("outs")),
                                "balls": _safe_int(ls_detail.get("balls")),
                                "strikes": _safe_int(ls_detail.get("strikes")),
                                "current_inning": _safe_int(ls_detail.get("currentInning")),
                                "inning_state": ls_detail.get("inningState", ""),
                                "inning_half": ls_detail.get("inningHalf", ""),
                                "is_top": ls_detail.get("isTopInning", True),
                                "inning_ordinal": ls_detail.get("inningOrdinal", ""),
                                "bases": {
                                    "first": bool(bases_raw.get("first", {}).get("occupied", False)) if isinstance(bases_raw.get("first"), dict) else False,
                                    "second": bool(bases_raw.get("second", {}).get("occupied", False)) if isinstance(bases_raw.get("second"), dict) else False,
                                    "third": bool(bases_raw.get("third", {}).get("occupied", False)) if isinstance(bases_raw.get("third"), dict) else False,
                                },
                                "current_pitcher_away": (ls_detail.get("defense", {}) or ls_detail.get("pitcher", {}) or {}).get("fullName", ""),
                                "current_pitcher_home": "",
                            },
                        }
        except Exception as e:
            logger.warning(f"MLB live fetch error: {e}")

        # LMB sportId=23
        try:
            r = await client.get(
                "https://statsapi.mlb.com/api/v1/schedule",
                params={"sportId": 23, "date": date_str, "hydrate": "linescore"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 200:
                for d in r.json().get("dates", []):
                    for g in d.get("games", []):
                        pk = str(g.get("gamePk"))
                        state = g.get("status", {}).get("detailedState", "")
                        ls = g.get("linescore", {})
                        teams = ls.get("teams", {}) if ls else {}
                        inning = ls.get("currentInning", "") if ls else ""
                        inning_state = ls.get("inningState", "") if ls else ""
                        is_final = state in ("Final", "Game Over", "Completed Early")
                        is_live = state in ("In Progress", "Live", "Delayed") or (
                            not is_final and state not in ("Scheduled", "Pre-Game", "Warmup", "")
                        )
                        display_inning = f"{inning_state} {inning}" if inning_state and inning else inning_state or inning or ""
                        innings_data = g.get("linescore", {}).get("innings", [])
                        ins = []
                        for inn in innings_data:
                            ins.append({
                                "num": inn.get("num", 0),
                                "away_runs": _safe_int(inn.get("away", {}).get("runs")),
                                "home_runs": _safe_int(inn.get("home", {}).get("runs")),
                                "away_hits": _safe_int(inn.get("away", {}).get("hits")),
                                "home_hits": _safe_int(inn.get("home", {}).get("hits")),
                                "away_errors": _safe_int(inn.get("away", {}).get("errors")),
                                "home_errors": _safe_int(inn.get("home", {}).get("errors")),
                            })
                        ls_detail = g.get("linescore", {})
                        bases_raw = g.get("linescore", {}).get("bases", {}) or g.get("bases", {})
                        away_team_obj = g.get("teams", {}).get("away", {}).get("team", {})
                        home_team_obj = g.get("teams", {}).get("home", {}).get("team", {})
                        live[pk] = {
                            "status": state,
                            "is_final": is_final,
                            "is_live": is_live,
                            "inning": inning or "",
                            "inning_state": inning_state or "",
                            "display_inning": display_inning,
                            "away_runs": _safe_int(teams.get("away", {}).get("runs")),
                            "home_runs": _safe_int(teams.get("home", {}).get("runs")),
                            "away_hits": _safe_int(teams.get("away", {}).get("hits")),
                            "home_hits": _safe_int(teams.get("home", {}).get("hits")),
                            "away_errors": _safe_int(teams.get("away", {}).get("errors")),
                            "home_errors": _safe_int(teams.get("home", {}).get("errors")),
                            "away_team_name": away_team_obj.get("name", ""),
                            "home_team_name": home_team_obj.get("name", ""),
                            "linescore": {
                                "innings": ins,
                                "outs": _safe_int(ls_detail.get("outs")),
                                "balls": _safe_int(ls_detail.get("balls")),
                                "strikes": _safe_int(ls_detail.get("strikes")),
                                "current_inning": _safe_int(ls_detail.get("currentInning")),
                                "inning_state": ls_detail.get("inningState", ""),
                                "inning_half": ls_detail.get("inningHalf", ""),
                                "is_top": ls_detail.get("isTopInning", True),
                                "inning_ordinal": ls_detail.get("inningOrdinal", ""),
                                "bases": {
                                    "first": bool(bases_raw.get("first", {}).get("occupied", False)) if isinstance(bases_raw.get("first"), dict) else False,
                                    "second": bool(bases_raw.get("second", {}).get("occupied", False)) if isinstance(bases_raw.get("second"), dict) else False,
                                    "third": bool(bases_raw.get("third", {}).get("occupied", False)) if isinstance(bases_raw.get("third"), dict) else False,
                                },
                                "current_pitcher_away": "",
                                "current_pitcher_home": "",
                            },
                        }
        except Exception as e:
            logger.warning(f"LMB live fetch error: {e}")

    return live


def _safe_int(v, default=0):
    try:
        return int(v) if v is not None else default
    except (ValueError, TypeError):
        return default


def run_initial_analysis():
    """Run full MLB + LMB analysis on startup. Synchronous."""
    logger.info("=== Inicializando análisis MLB ===")
    try:
        from scheduler import tarea_analisis_manana
        tarea_analisis_manana()
    except Exception as e:
        logger.error(f"MLB initial analysis error: {e}")

    if getattr(config, "LMB_ACTIVO", False):
        logger.info("=== Inicializando análisis LMB ===")
        try:
            result = analizar_lmb_dia()
            if result:
                dm.guardar_analisis_lmb(result)
                dm.guardar_estado_lmb(result)
                logger.info(f"LMB análisis inicial: {len(result)} partidos")
        except Exception as e:
            logger.error(f"LMB initial analysis error: {e}")

    _cache["live_data"] = {}


async def ciclo_actualizacion(ws_manager):
    """Main async loop: every 60s fetch live scores and broadcast."""
    logger.info("=== Ciclo de actualización en vivo iniciado ===")

    while True:
        try:
            live = await fetch_live_data()
            _cache["live_data"] = live

            # Check for newly finished games → update CSV
            estado = dm.cargar_estado()
            for p in estado:
                pk = str(p.get("game_pk", ""))
                if pk in live and live[pk].get("is_final"):
                    if p.get("resultado") in ("acertado", "fallido"):
                        continue
                    # Update CSV
                    ar = live[pk].get("away_runs", 0)
                    hr = live[pk].get("home_runs", 0)
                    away_name = p.get("away_team", "")
                    home_name = p.get("home_team", "")
                    ganador = away_name if ar > hr else home_name
                    marcador = f"{away_name} {ar} - {hr} {home_name}"
                    dm.actualizar_resultado(int(pk), ganador, marcador)
                    def _match(a, b):
                        a, b = a.strip().lower(), b.strip().lower()
                        return a == b or a in b or b in a
                    acertado = _match(ganador, p.get("favorito", ""))
                    dm.actualizar_estado_resultado(int(pk), "acertado" if acertado else "fallido", ganador)
                    logger.info(f"Resultado actualizado: {marcador} -> {'acertado' if acertado else 'fallido'}")

            # Broadcast to all WebSocket clients
            data = _build_data()
            await ws_manager.broadcast({"type": "full_update", "data": data})

        except Exception as e:
            logger.error(f"Error en ciclo actualización: {e}")

        await asyncio.sleep(60)
