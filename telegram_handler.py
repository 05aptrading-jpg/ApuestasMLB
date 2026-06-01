"""
Telegram command handler.
Escucha comandos /actualizar y responde con tabla compacta de resultados.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime

import requests

import config
import data_manager as dm
from api_client import mlb
import bot

logger = logging.getLogger(__name__)

TELEGRAM_URL = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}"
_last_update_id = 0

RAILWAY_API_URL = "https://backboard.railway.app/graphql"


MINIAPP_URL = "https://05aptrading-jpg.github.io/ApuestasMLB/"

DISCLAIMER = "📚 MLB Analytics — Análisis académico basado en datos públicos. No constituye consejo financiero ni de apuestas."

# ── Cargar / guardar suscriptores ─────────────────────────────────────
SUSCRIPTORES_PATH = os.path.join(os.path.dirname(__file__), "suscriptores.json")


def _cargar_suscriptores() -> dict:
    try:
        with open(SUSCRIPTORES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        # Migrar formato antiguo (autorizados: [ids]) -> nuevo (suscripciones: {})
        if "autorizados" in data and "suscripciones" not in data:
            from datetime import date as _date, timedelta
            expira = (_date.today() + timedelta(days=30)).isoformat()
            suscripciones = {}
            for uid in data.get("autorizados", []):
                uid_str = str(uid)
                if uid_str == str(data.get("admin_id")):
                    suscripciones[uid_str] = None
                else:
                    suscripciones[uid_str] = expira
            data["suscripciones"] = suscripciones
            del data["autorizados"]
            _guardar_suscriptores(data)
        return data
    except Exception:
        return {"admin_id": 0, "suscripciones": {}}


def _guardar_suscriptores(data: dict):
    try:
        with open(SUSCRIPTORES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error guardando suscriptores: {e}")


def _expirar_vencidos(data: dict):
    from datetime import date as _date
    hoy = _date.today().isoformat()
    suscripciones = data.get("suscripciones", {})
    vencidos = [uid for uid, exp in suscripciones.items()
                if exp is not None and exp < hoy]
    for uid in vencidos:
        del suscripciones[uid]
        logger.info(f"Suscripción vencida — usuario {uid} eliminado")
    if vencidos:
        data["suscripciones"] = suscripciones
        _guardar_suscriptores(data)
    return data


def _esta_autorizado(chat_id: int) -> bool:
    data = _cargar_suscriptores()
    data = _expirar_vencidos(data)
    admin = data.get("admin_id", 0)
    if chat_id == admin:
        return True
    uid_str = str(chat_id)
    suscripciones = data.get("suscripciones", {})
    if uid_str not in suscripciones:
        return False
    expira = suscripciones[uid_str]
    if expira is None:
        return True
    from datetime import date as _date
    return expira >= _date.today().isoformat()


# ── Envío de mensajes ─────────────────────────────────────────────────
def _send_raw(chat_id: str, text: str, mini_app: bool = False):
    import requests as _r
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if mini_app and config.GITHUB_TOKEN:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [[{
                "text": "📱 Abrir Mini App",
                "web_app": {"url": MINIAPP_URL},
            }]],
        })
    try:
        _r.post(url, json=payload, timeout=10)
    except Exception:
        pass


# ── Comandos ──────────────────────────────────────────────────────────
def _cmd_actualiza(chat_id: str):
    """Ejecuta /actualizar: consulta ESPN y muestra resultados + rendimiento."""
    from datetime import date as _date, timedelta
    hoy = _date.today()
    ayer = hoy - timedelta(days=1)
    lineas = [
        "📊 <b>MLB BOT — ACTUALIZACIÓN</b>",
        f"📅 {hoy.strftime('%d/%m/%Y')}",
        "",
    ]

    # Consultar ESPN para hoy y ayer
    def _espn_scoreboard(fecha: _date) -> list:
        try:
            ds = fecha.strftime("%Y%m%d")
            url = f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={ds}"
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                return []
            games = []
            for ev in r.json().get("events", []):
                comp = (ev.get("competitions") or [{}])[0]
                comps = comp.get("competitors", [])
                h = next((c for c in comps if c.get("homeAway") == "home"), None)
                a = next((c for c in comps if c.get("homeAway") == "away"), None)
                if not h or not a:
                    continue
                hn = h.get("team", {}).get("displayName", "")
                an = a.get("team", {}).get("displayName", "")
                detail = comp.get("status", {}).get("type", {}).get("detail", "")
                done = comp.get("status", {}).get("type", {}).get("completed", False)
                ar = int(a.get("score", 0) or 0)
                hr = int(h.get("score", 0) or 0)
                games.append({"a": an, "h": hn, "ar": ar, "hr": hr, "detail": detail, "done": done})
            return games
        except Exception:
            return []

    def _t_sep():
        return "┌─────┬──────────────────────────────────┬──────────┐"

    def _t_row(emoji, equipos, estado):
        e = emoji.ljust(5)
        eq = equipos.ljust(32)
        es = estado.ljust(10)
        return f"│ {e}│ {eq}│ {es}│"

    all_games = _espn_scoreboard(hoy) + _espn_scoreboard(ayer)

    if not all_games:
        lineas.append("ℹ️ Sin partidos disponibles vía ESPN.")
    else:
        # Ordenar: hoy primero, luego ayer
        hoy_games = [g for g in all_games if "Final" not in g["detail"] or "Aplazado" in g["detail"]]
        ayer_games = [g for g in all_games if g not in hoy_games]
        # Mostrar pendientes/en vivo primero
        pendientes = [g for g in hoy_games if not g["done"]]
        finalizados_hoy = [g for g in hoy_games if g["done"]]
        ordenados = pendientes + finalizados_hoy + ayer_games

        for g in ordenados[:15]:
            if g["done"]:
                emoji = "✅" if int(g["ar"]) != int(g["hr"]) else "🤝"  # no hay favorito, mostrar resultado
                score = f"{g['ar']}-{g['hr']}"
                state = g["detail"][:10]
            elif "Postp" in g["detail"] or "Aplaz" in g["detail"]:
                emoji = "🚫"
                score = "—"
                state = "Posp."
            elif "progr" in g["detail"].lower() or "sched" in g["detail"].lower():
                emoji = "⏳"
                score = "—"
                state = g["detail"][:10]
            else:
                emoji = "🔴"
                score = f"{g['ar']}-{g['hr']}"
                state = g["detail"][:10]
            equipos = f"{g['a']} {score} {g['h']}"
            lineas.append(_t_sep())
            lineas.append(_t_row(emoji, equipos, state))
        lineas.append("└─────┴──────────────────────────────────┴──────────┘")

    # ── Estadísticas históricas ──
    lineas += ["", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    stats = dm.obtener_estadisticas()
    if stats["total"] > 0:
        lineas += [
            "📊 <b>MLB BOT — RENDIMIENTO</b>",
            f"🌐 Global: {stats['acertados']}✅ {stats['fallidos']}❌ ({stats['total']}) → <b>{stats['win_rate']}%</b>",
        ]
        if stats["alta_total"] > 0:
            rw = stats['alta_win_rate']
            extra = " 🔥" if rw >= 65 else ""
            lineas += [f"🎯 Alta Confianza: {stats['alta_acertados']}✅ {stats['alta_fallidos']}❌ ({stats['alta_total']}) → <b>{rw}%</b>{extra}"]
        if stats["media_total"] > 0:
            lineas += [f"📊 Conf. Media: {stats['media_acertados']}✅ {stats['media_fallidos']}❌ ({stats['media_total']}) → <b>{stats['media_win_rate']}%</b>"]
        if stats["baja_total"] > 0:
            lineas += [f"📋 Solo Inform.: {stats['baja_acertados']}✅ {stats['baja_fallidos']}❌ ({stats['baja_total']}) → <b>{stats['baja_win_rate']}%</b>"]
        lineas += [f"⭐ Señales Valor: {stats['valor_ok']}/{stats['valor_total']} ({stats['valor_rate']}%)"]

    show_mini = bool(config.GITHUB_TOKEN)
    text = "\n".join(lineas)
    if len(text) <= 4000:
        _send_raw(chat_id, text, mini_app=show_mini)
    else:
        for parte in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            _send_raw(chat_id, parte, mini_app=False)





def _cmd_suscriptores(chat_id: int, args: str):
    data = _cargar_suscriptores()
    data = _expirar_vencidos(data)
    admin = data.get("admin_id", 0)
    if chat_id != admin:
        _send_raw(str(chat_id), "⛔ Solo el administrador puede gestionar suscriptores.")
        return

    suscripciones = data.get("suscripciones", {})
    partes = args.strip().split()
    if not partes:
        from datetime import date as _date
        hoy = _date.today()
        lineas = []
        for uid_str, expira in suscripciones.items():
            if expira is None:
                lineas.append(f"  • {uid_str} (permanente)")
            else:
                dias_rest = (_date.fromisoformat(expira) - hoy).days
                lineas.append(f"  • {uid_str} (expira {expira}, restan {dias_rest}d)")
        _send_raw(str(chat_id),
            f"📋 <b>Suscriptores ({len(suscripciones)})</b>\n" + "\n".join(lineas) or "  (vacía)")
        return

    subcmd = partes[0].lower()
    if subcmd == "add" and len(partes) >= 2:
        try:
            uid = int(partes[1])
            uid_str = str(uid)
            from datetime import date as _date, timedelta
            expira = (_date.today() + timedelta(days=30)).isoformat()
            if uid_str in suscripciones and suscripciones[uid_str] is not None:
                suscripciones[uid_str] = expira
                _send_raw(str(chat_id), f"✅ Suscripción de {uid} renovada hasta {expira}.")
            elif uid_str in suscripciones and suscripciones[uid_str] is None:
                _send_raw(str(chat_id), f"ℹ️ {uid} ya tiene acceso permanente.")
                return
            else:
                suscripciones[uid_str] = expira
                _send_raw(str(chat_id), f"✅ Usuario {uid} añadido hasta {expira}.")
            data["suscripciones"] = suscripciones
            _guardar_suscriptores(data)
        except ValueError:
            _send_raw(str(chat_id), "❌ ID inválido. Usa: /suscriptores add <ID>")
        return

    if subcmd == "del" and len(partes) >= 2:
        uid_str = partes[1]
        if uid_str in suscripciones:
            del suscripciones[uid_str]
            data["suscripciones"] = suscripciones
            _guardar_suscriptores(data)
            _send_raw(str(chat_id), f"🗑️ Usuario {uid_str} eliminado.")
        else:
            _send_raw(str(chat_id), f"❌ {uid_str} no está en la lista.")
        return

    _send_raw(str(chat_id), "❌ Usa: /suscriptores add <ID> | del <ID> | (sin args para listar)")


def _cmd_deploy(chat_id: int):
    """Trigger Railway redeploy via GraphQL API."""
    data = _cargar_suscriptores()
    admin = data.get("admin_id", 0)
    if chat_id != admin:
        _send_raw(str(chat_id), "⛔ Solo el administrador puede hacer deploy.")
        return

    token = config.RAILWAY_API_TOKEN
    project_id = config.RAILWAY_PROJECT_ID
    service_id = config.RAILWAY_SERVICE_ID

    if not token:
        _send_raw(str(chat_id), "❌ Falta RAILWAY_API_TOKEN en config.")
        return

    _send_raw(str(chat_id), "🚀 Iniciando deploy en Railway...")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        if service_id:
            query = """
            mutation {
              serviceInstanceDeploy(input: { serviceId: "%s" }) {
                id
                status
              }
            }
            """ % service_id
        elif project_id:
            query = """
            mutation {
              deploymentTrigger(input: { projectId: "%s" }) {
                id
                status
              }
            }
            """ % project_id
        else:
            _send_raw(str(chat_id),
                "❌ Faltan RAILWAY_PROJECT_ID o RAILWAY_SERVICE_ID en config.\n"
                "Agrégalos como variables de entorno en Railway.")
            return

        r = requests.post(RAILWAY_API_URL, json={"query": query},
                          headers=headers, timeout=30)
        result = r.json()

        if result.get("errors"):
            err_msg = result["errors"][0].get("message", "Error desconocido")
            _send_raw(str(chat_id), f"❌ Error Railway API:\n{err_msg}")
            return

        deploy_data = (result.get("data", {}).get("serviceInstanceDeploy")
                       or result.get("data", {}).get("deploymentTrigger"))
        if deploy_data:
            dep_id = deploy_data.get("id", "?")
            status = deploy_data.get("status", "queued")
            _send_raw(str(chat_id),
                f"✅ Deploy disparado!\n"
                f"🆔 ID: {dep_id}\n"
                f"📊 Estado: {status}\n\n"
                f"El bot se reiniciará automáticamente en ~60s.")
        else:
            _send_raw(str(chat_id),
                f"⚠️ Respuesta inesperada:\n{str(result)[:500]}")

    except Exception as e:
        logger.error(f"Deploy error: {e}")
        _send_raw(str(chat_id), f"❌ Error conectando a Railway:\n{e}")


# ── Procesador de updates ─────────────────────────────────────────────
def handle_updates():
    global _last_update_id
    logger.info("Telegram handler: polling iniciado")
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates"

    while True:
        try:
            r = requests.get(url, params={
                "offset": _last_update_id,
                "timeout": 10,
                "allowed_updates": json.dumps(["message"]),
            }, timeout=15)
            if r.status_code != 200:
                time.sleep(5)
                continue
            updates = r.json().get("result", [])
            for upd in updates:
                _last_update_id = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat_id = msg.get("chat", {}).get("id")
                if not chat_id:
                    continue

                text = (msg.get("text") or "").strip()
                if not text:
                    continue

                # /start
                if text.startswith("/start"):
                    if _esta_autorizado(chat_id):
                        data = _cargar_suscriptores()
                        es_admin = chat_id == data.get("admin_id", 0)
                        cmds = (
                            "📊 <b>Comandos disponibles:</b>\n"
                            "  /actualizar — Ver resultados del día\n"
                            "  /suscribirse — Abrir Mini App"
                        )
                        if es_admin:
                            cmds += "\n  /deploy — Redeploy Railway"
                        _send_raw(str(chat_id),
                            "⚾ <b>MLB Analytics</b>\n\n"
                            "Bienvenido al sistema de análisis MLB.\n\n"
                            + cmds,
                            mini_app=True
                        )
                    else:
                        _send_raw(str(chat_id),
                            "⚾ <b>MLB Analytics</b>\n\n"
                            "Bienvenido.\n\n"
                            "🔒 Acceso exclusivo para suscriptores.\n"
                            f"Contacta a @{config.ADMIN_USERNAME} para obtener acceso.",
                            mini_app=True
                        )
                    continue

                # /actualizar
                if text.startswith("/actualizar"):
                    if _esta_autorizado(chat_id):
                        _cmd_actualiza(str(chat_id))
                    else:
                        _send_raw(str(chat_id),
                            "🔒 Acceso restringido.\n"
                            f"Contacta a @{config.ADMIN_USERNAME} para obtener acceso.",
                            mini_app=True
                        )
                    continue

                # /suscribirse — alias para enlace a Mini App
                if text.startswith("/suscribirse") or text.startswith("/suscriptores"):
                    if chat_id:
                        _cmd_suscriptores(chat_id, text[len("/suscriptores"):].strip())
                    continue

                # /deploy — solo admin
                if text.startswith("/deploy"):
                    _cmd_deploy(chat_id)
                    continue

        except Exception as e:
            logger.error(f"Telegram handler error: {e}")
            time.sleep(5)


def iniciar():
    """Arranca el handler en un thread daemon. Configura el Menu Button de Mini App."""
    # Botón permanente de Mini App en la barra de input del chat
    try:
        requests.post(
            f"{TELEGRAM_URL}/setChatMenuButton",
            json={
                "menu_button": {
                    "type": "web_app",
                    "text": "📱 Mini App",
                    "web_app": {"url": MINIAPP_URL},
                }
            },
            timeout=5,
        )
    except Exception as e:
        logger.warning(f"No se pudo configurar Menu Button: {e}")
    hilo = threading.Thread(target=handle_updates, daemon=True, name="telegram-cmd")
    hilo.start()
    logger.info("Telegram handler: thread iniciado")
