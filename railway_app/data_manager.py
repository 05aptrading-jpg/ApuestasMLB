"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  MLB BOT — data_manager.py                                                  ║
║  Gestión del CSV de historial y estado de partidos en seguimiento           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import csv
import hashlib
import json
import logging
import os
from datetime import datetime, date
from typing import Optional

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger(__name__)


def _lmb_game_pk(away: str, home: str, fecha: str) -> int:
    """ID determinístico positivo para LMB (hash() no es determinístico)."""
    raw = hashlib.md5("|".join([away, home, fecha]).encode()).hexdigest()
    return int(raw[:16], 16)


# ─────────────────────────────────────────────────────────────────────────────
# ESQUEMA CSV
# ─────────────────────────────────────────────────────────────────────────────
CSV_COLUMNAS = [
    "id_partido",           # gamePk de MLB Stats API
    "liga",                 # MLB | LMB
    "fecha_hora",           # ISO datetime del partido
    "equipo_visitante",
    "equipo_local",
    "abridor_visitante",
    "abridor_local",
    "favorito_sabermetrico",
    "probabilidad_inicial", # % calculado por el bot
    "prob_mercado",         # % implícita de The Odds API
    "es_valor",             # True si cumple la Tríada del Valor
    "factor_riesgo",
    # Scores por bloque
    "score_b1_pitcheo_away", "score_b1_pitcheo_home",
    "score_b2_ofensiva_away", "score_b2_ofensiva_home",
    "score_b3_bullpen_away", "score_b3_bullpen_home",
    "score_b4_eficiencia_away", "score_b4_eficiencia_home",
    # Métricas clave
    "fip_away", "xfip_away", "kbb_away",
    "fip_home", "xfip_home", "kbb_home",
    "wrc_away", "wrc_home",
    "war_bullpen_away", "war_bullpen_home",
    "pitcheos_72h_away", "pitcheos_72h_home",
    "baseruns_diff_away", "baseruns_diff_home",
    # Resultado
    "descripcion_analisis",
    "resultado",            # "acertado" | "fallido" | "pendiente"
    "probabilidad_actualizada",
    "marcador_final",
    "ganador_real",
    "fecha_actualizacion",
]

STATE_PATH = os.path.join(BASE_DIR, "partidos_seguimiento.json")


# ─────────────────────────────────────────────────────────────────────────────
# INICIALIZACIÓN
# ─────────────────────────────────────────────────────────────────────────────
def inicializar_csv():
    """Crea el CSV con encabezados si no existe."""
    if not os.path.exists(config.CSV_PATH):
        with open(config.CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_COLUMNAS).writeheader()
        logger.info(f"CSV creado: {config.CSV_PATH}")
    else:
        logger.info(f"CSV existente: {config.CSV_PATH}")


# ─────────────────────────────────────────────────────────────────────────────
# GUARDAR ANÁLISIS DEL DÍA
# ─────────────────────────────────────────────────────────────────────────────
def guardar_analisis(analyses: list[GameAnalysis]):
    """
    Guarda todos los análisis del día en el CSV.
    Solo escribe si el game_pk no existe ya en el CSV (evita duplicados).
    También deduplica dentro de la lista por (away_team, home_team, fecha)
    para manejar game_pks distintos del mismo partido (dobleheaders falsos,
    cambios de pk en la API MLB).
    """
    existentes = _leer_ids_existentes()

    # Deduplicar por (away_team, home_team, fecha) antes de escribir
    _vistos: set = set()
    analyses_dedup: list = []
    for a in sorted(analyses, key=lambda x: x.prob_favorito, reverse=True):
        clave = (a.away_team.strip().lower(), a.home_team.strip().lower(), a.game_date[:10])
        if clave not in _vistos:
            _vistos.add(clave)
            analyses_dedup.append(a)
        else:
            logger.info(
                f"Dedup CSV: {a.away_team} @ {a.home_team} {a.game_date[:10]} "
                f"— game_pk={a.game_pk} descartado (duplicado)"
            )

    nuevos = 0
    with open(config.CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNAS)
        for a in analyses_dedup:
            if str(a.game_pk) in existentes:
                logger.debug(f"Partido {a.game_pk} ya existe en CSV — omitido")
                continue

            away_p = a.away_pitcher
            home_p = a.home_pitcher
            away_o = a.away_offense
            home_o = a.home_offense
            away_b = a.away_bullpen
            home_b = a.home_bullpen
            away_e = a.away_efficiency
            home_e = a.home_efficiency

            desc = _generar_descripcion(a)

            fila = {
                "id_partido":               str(a.game_pk),
                "liga":                     getattr(a, "liga", "MLB"),
                "fecha_hora":               a.game_date,
                "equipo_visitante":         a.away_team,
                "equipo_local":             a.home_team,
                "abridor_visitante":        away_p.name if away_p else "TBD",
                "abridor_local":            home_p.name if home_p else "TBD",
                "favorito_sabermetrico":    a.favorito,
                "probabilidad_inicial":     f"{a.prob_favorito:.2f}%",
                "prob_mercado":             f"{a.odds_mercado:.2f}%" if a.odds_mercado else "N/D",
                "es_valor":                 "SI" if a.es_valor else "NO",
                "factor_riesgo":            a.factor_riesgo,
                "score_b1_pitcheo_away":    f"{a.away_score_b1:.1f}",
                "score_b1_pitcheo_home":    f"{a.home_score_b1:.1f}",
                "score_b2_ofensiva_away":   f"{a.away_score_b2:.1f}",
                "score_b2_ofensiva_home":   f"{a.home_score_b2:.1f}",
                "score_b3_bullpen_away":    f"{a.away_score_b3:.1f}",
                "score_b3_bullpen_home":    f"{a.home_score_b3:.1f}",
                "score_b4_eficiencia_away": f"{a.away_score_b4:.1f}",
                "score_b4_eficiencia_home": f"{a.home_score_b4:.1f}",
                "fip_away":      f"{away_p.fip:.2f}"  if away_p else "N/D",
                "xfip_away":     f"{away_p.xfip:.2f}" if away_p else "N/D",
                "kbb_away":      f"{away_p.k_pct - away_p.bb_pct:.1f}%" if away_p else "N/D",
                "fip_home":      f"{home_p.fip:.2f}"  if home_p else "N/D",
                "xfip_home":     f"{home_p.xfip:.2f}" if home_p else "N/D",
                "kbb_home":      f"{home_p.k_pct - home_p.bb_pct:.1f}%" if home_p else "N/D",
                "wrc_away":      f"{away_o.wrc_plus:.0f}" if away_o else "N/D",
                "wrc_home":      f"{home_o.wrc_plus:.0f}" if home_o else "N/D",
                "war_bullpen_away":   f"{away_b.war_bullpen:.2f}" if away_b else "N/D",
                "war_bullpen_home":   f"{home_b.war_bullpen:.2f}" if home_b else "N/D",
                "pitcheos_72h_away":  str(away_b.pitcheos_72h) if away_b else "0",
                "pitcheos_72h_home":  str(home_b.pitcheos_72h) if home_b else "0",
                "baseruns_diff_away": f"{away_e.diferencial:.1f}" if away_e else "N/D",
                "baseruns_diff_home": f"{home_e.diferencial:.1f}" if home_e else "N/D",
                "descripcion_analisis":     desc,
                "resultado":                "pendiente",
                "probabilidad_actualizada": f"{a.prob_favorito:.2f}%",
                "marcador_final":           "—",
                "ganador_real":             "—",
                "fecha_actualizacion":      datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            writer.writerow(fila)
            nuevos += 1

    logger.info(f"CSV: {nuevos} partidos nuevos guardados")


# ─────────────────────────────────────────────────────────────────────────────
# GUARDAR ANÁLISIS LMB
# ─────────────────────────────────────────────────────────────────────────────
def _fmt_metric(val):
    """Formatea un valor metrico: None/N/D si es None, str si tiene valor."""
    if val is None:
        return "N/D"
    if isinstance(val, float):
        return f"{val:.2f}"
    return str(val)


def guardar_analisis_lmb(analyses: list[dict]):
    """
    Guarda/actualiza análisis LMB en el CSV.
    - Si el game_pk ya existe → actualiza la fila (reemplaza datos, conserva resultado)
    - Si no existe → agrega fila nueva
    Así el CSV siempre refleja el análisis más reciente.
    """
    filas = _leer_todas()
    # Limpiar entradas LMB viejas (IDs hash simulados)
    filas = [r for r in filas
             if not (r.get("liga") == "LMB" and len(r.get("id_partido","")) > 10)]
    idx_por_pk = {r["id_partido"]: i for i, r in enumerate(filas)}
    nuevos = 0
    actualizados = 0

    for a in analyses:
        pk = str(a.get("game_pk",
                      _lmb_game_pk(a.get("away_team",""),
                                   a.get("home_team",""),
                                   a.get("game_date",""))))
        fecha_base = a.get("game_date", "")
        hora = a.get("game_time", "")
        fecha_hora_val = f"{fecha_base} {hora}" if hora else fecha_base
        fila = {
            "id_partido":               pk,
            "liga":                     "LMB",
            "fecha_hora":               fecha_hora_val,
            "equipo_visitante":         a.get("away_team", ""),
            "equipo_local":             a.get("home_team", ""),
            "abridor_visitante":        a.get("away_pitcher", "N/D"),
            "abridor_local":            a.get("home_pitcher", "N/D"),
            "favorito_sabermetrico":    a.get("favorito", ""),
            "probabilidad_inicial":     f'{a.get("prob_favorito", 0):.2f}%',
            "prob_mercado":             "N/D",
            "es_valor":                 "NO",
            "factor_riesgo":            a.get("factor_riesgo", "Bajo"),
            "score_b1_pitcheo_away":    f'{a.get("score_b1_away", 0):.1f}',
            "score_b1_pitcheo_home":    f'{a.get("score_b1_home", 0):.1f}',
            "score_b2_ofensiva_away":   f'{a.get("score_b2_away", 0):.1f}',
            "score_b2_ofensiva_home":   f'{a.get("score_b2_home", 0):.1f}',
            "score_b3_bullpen_away":    f'{a.get("score_b3_away", 0):.1f}',
            "score_b3_bullpen_home":    f'{a.get("score_b3_home", 0):.1f}',
            "score_b4_eficiencia_away": f'{a.get("score_b4_away", 0):.1f}',
            "score_b4_eficiencia_home": f'{a.get("score_b4_home", 0):.1f}',
            "fip_away":             _fmt_metric(a.get("fip_away")),
            "xfip_away":            _fmt_metric(a.get("xfip_away")),
            "kbb_away":             _fmt_metric(a.get("kbb_away")),
            "fip_home":             _fmt_metric(a.get("fip_home")),
            "xfip_home":            _fmt_metric(a.get("xfip_home")),
            "kbb_home":             _fmt_metric(a.get("kbb_home")),
            "wrc_away":             _fmt_metric(a.get("wrc_away")),
            "wrc_home":             _fmt_metric(a.get("wrc_home")),
            "war_bullpen_away":     _fmt_metric(a.get("war_bullpen_away")),
            "war_bullpen_home":     _fmt_metric(a.get("war_bullpen_home")),
            "pitcheos_72h_away": "0", "pitcheos_72h_home": "0",
            "baseruns_diff_away": "N/D", "baseruns_diff_home": "N/D",
            "descripcion_analisis":     a.get("descripcion", ""),
            "resultado":                "pendiente",
            "probabilidad_actualizada": f'{a.get("prob_favorito", 0):.2f}%',
            "marcador_final":           "-",
            "ganador_real":             "-",
            "fecha_actualizacion":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        if pk in idx_por_pk:
            idx = idx_por_pk[pk]
            resultado_previo = filas[idx].get("resultado", "pendiente")
            fila["resultado"]          = filas[idx]["resultado"]
            fila["marcador_final"]     = filas[idx].get("marcador_final", "—")
            fila["ganador_real"]       = filas[idx].get("ganador_real", "—")
            fila["fecha_actualizacion"] = filas[idx].get("fecha_actualizacion", "")
            filas[idx] = fila
            actualizados += 1
        else:
            filas.append(fila)
            nuevos += 1

    _escribir_todas(filas)
    logger.info(f"CSV LMB: {nuevos} nuevos, {actualizados} actualizados")


# ─────────────────────────────────────────────────────────────────────────────
# ELIMINAR PARTIDO POSPUESTO
# ─────────────────────────────────────────────────────────────────────────────
def _guardar_estado_raw(estado: list):
    """Escribe directamente la lista al JSON sin procesamiento adicional."""
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2, default=str)


def eliminar_partido(game_pk: int, away_team: str = "", home_team: str = "", fecha: str = ""):
    """
    Elimina un partido pospuesto/cancelado del CSV y del JSON de seguimiento.
    Busca por (equipo_visitante, equipo_local, fecha) — robusto ante pk mismatch.
    """
    def _match(a: str, b: str) -> bool:
        a, b = a.strip().lower(), b.strip().lower()
        return a == b or a in b or b in a

    def _es_partido(fila_away, fila_home, fila_fecha):
        por_equipo = (
            away_team and home_team and fecha and
            fila_fecha == fecha and
            _match(away_team, fila_away) and
            _match(home_team, fila_home)
        )
        return por_equipo

    # ── Eliminar del CSV ──────────────────────────────────────────────────
    filas = _leer_todas()
    filas_nuevas = [
        f for f in filas
        if not _es_partido(
            f.get("equipo_visitante", ""),
            f.get("equipo_local", ""),
            f.get("fecha_hora", "")[:10],
        ) and f.get("id_partido") != str(game_pk)
    ]
    eliminados_csv = len(filas) - len(filas_nuevas)
    if eliminados_csv:
        _escribir_todas(filas_nuevas)
        logger.info(f"CSV: eliminado partido pospuesto — {away_team} @ {home_team} {fecha}")
    else:
        logger.warning(f"CSV: partido pospuesto no encontrado — pk={game_pk} {away_team}@{home_team}")

    # ── Eliminar del JSON de seguimiento ─────────────────────────────────
    estado = cargar_estado()
    estado_nuevo = [
        p for p in estado
        if not _es_partido(
            p.get("away_team", ""),
            p.get("home_team", ""),
            p.get("game_date", "")[:10],
        ) and p.get("game_pk") != game_pk
    ]
    eliminados_json = len(estado) - len(estado_nuevo)
    if eliminados_json:
        _guardar_estado_raw(estado_nuevo)
        logger.info(f"JSON: eliminado partido pospuesto — {away_team} @ {home_team} {fecha}")
    else:
        logger.warning(f"JSON: partido pospuesto no encontrado — pk={game_pk}")


# ─────────────────────────────────────────────────────────────────────────────
# ACTUALIZAR RESULTADO
# ─────────────────────────────────────────────────────────────────────────────
def actualizar_resultado(game_pk: int, ganador: str,
                          marcador: str, prob_nueva: float = None):
    """
    Actualiza la columna 'resultado' y 'marcador_final' para un partido.
    Lee el CSV completo, modifica la fila y lo reescribe.
    """
    filas = _leer_todas()
    modificado = False

    def _match(a: str, b: str) -> bool:
        a, b = a.strip().lower(), b.strip().lower()
        return a == b or a in b or b in a

    for fila in filas:
        if fila["id_partido"] == str(game_pk):
            favorito = fila["favorito_sabermetrico"]
            resultado = "acertado" if _match(ganador, favorito) else "fallido"
            fila["resultado"]            = resultado
            fila["marcador_final"]       = marcador
            fila["ganador_real"]         = ganador
            fila["fecha_actualizacion"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
            if prob_nueva is not None:
                fila["probabilidad_actualizada"] = f"{prob_nueva:.2f}%"
            modificado = True
            logger.info(f"Partido {game_pk} → {resultado} ({ganador})")
            break

    if modificado:
        _escribir_todas(filas)
    else:
        logger.warning(f"game_pk {game_pk} no encontrado en CSV")


def actualizar_odds(game_pk: int, prob_nueva: float):
    """
    Actualiza la probabilidad cuando cambia más de X% (alerta de cuotas).
    """
    filas = _leer_todas()
    for fila in filas:
        if fila["id_partido"] == str(game_pk):
            fila["probabilidad_actualizada"] = f"{prob_nueva:.2f}%"
            fila["fecha_actualizacion"]      = datetime.now().strftime("%Y-%m-%d %H:%M")
            break
    _escribir_todas(filas)


# ─────────────────────────────────────────────────────────────────────────────
# ESTADO DE SEGUIMIENTO (JSON)
# ─────────────────────────────────────────────────────────────────────────────
def guardar_estado(analyses: list[GameAnalysis]):
    """
    Guarda el estado de los partidos del día en JSON.
    Solo incluye los partidos analizados hoy — no arrastra pendientes de días anteriores.

    Estados posibles:
      pendiente   → partido aún no jugado
      pospuesto   → partido pospuesto/cancelado (no volver a consultar)
      acertado / fallido / no_encontrado → resueltos
    """
    ESTADOS_FINALES = {"acertado", "fallido", "no_encontrado", "pospuesto"}

    # ── Deduplicar por (away_team, home_team, fecha) — evita game_pks dobles
    _vistos: set = set()
    analyses_dedup: list = []
    for a in sorted(analyses, key=lambda x: x.prob_favorito, reverse=True):
        clave = (a.away_team.strip().lower(), a.home_team.strip().lower(), a.game_date[:10])
        if clave not in _vistos:
            _vistos.add(clave)
            analyses_dedup.append(a)
        else:
            logger.info(
                f"Dedup estado: {a.away_team} @ {a.home_team} {a.game_date[:10]} "
                f"— game_pk={a.game_pk} descartado (duplicado)"
            )

    # ── Cargar estado existente
    existente = cargar_estado()
    existente_idx = {p["game_pk"]: p for p in existente}

    # Partidos de hoy
    estado = []
    for a in analyses_dedup:
        game_dt = getattr(a, "game_datetime", None) or a.game_date

        # Si ya existía con un estado final, respetarlo (no sobreescribir con 'pendiente')
        ya_existente = existente_idx.get(a.game_pk, {})
        resultado_previo = ya_existente.get("resultado", "pendiente")
        if resultado_previo in ESTADOS_FINALES:
            estado.append(ya_existente)
            logger.debug(
                f"Estado: game_pk={a.game_pk} ya resuelto como "
                f"'{resultado_previo}' — conservado sin cambios"
            )
            continue

        estado.append({
            "game_pk":       a.game_pk,
            "game_date":     a.game_date,
            "game_datetime": game_dt,
            "away_team":     a.away_team,
            "home_team":     a.home_team,
            "favorito":      a.favorito,
            "prob_favorito": a.prob_favorito,
            "odds_mercado":  a.odds_mercado,
            "es_valor":      a.es_valor,
            "resultado":     "pendiente",
        })

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    logger.info(
        f"Estado guardado: {STATE_PATH} — {len(analyses)} partidos de hoy"
    )


def cargar_estado() -> list[dict]:
    """Carga el estado de seguimiento del día."""
    if not os.path.exists(STATE_PATH):
        return []
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error cargando estado: {e}")
        return []


def guardar_estado_lmb(analyses: list[dict]):
    """Guarda estado de partidos LMB en seguimiento (update-in-place)."""
    estado = cargar_estado()
    # Remover entradas LMB viejas con IDs hash (simuladas)
    estado = [p for p in estado
              if not (p.get("liga") == "LMB" and len(str(p.get("game_pk",""))) > 10)]

    existente_pk = {p["game_pk"] for p in estado}
    nuevos = 0
    actualizados = 0
    for a in analyses:
        pk = a.get("game_pk",
                    _lmb_game_pk(a.get("away_team",""),
                                 a.get("home_team",""),
                                 a.get("game_date","")))
        game_datetime = f"{a.get('game_date','')} {a.get('game_time','')}".strip()
        entry = {
            "game_pk":       pk,
            "liga":          "LMB",
            "game_date":     a.get("game_date", ""),
            "game_datetime": game_datetime,
            "away_team":     a.get("away_team", ""),
            "home_team":     a.get("home_team", ""),
            "away_pitcher":  a.get("away_pitcher", "N/D"),
            "home_pitcher":  a.get("home_pitcher", "N/D"),
            "favorito":      a.get("favorito", ""),
            "prob_favorito": a.get("prob_favorito", 0),
            "odds_mercado":  None,
            "es_valor":      False,
            "resultado":     "pendiente",
            "marcador":      None,
        }
        if pk in existente_pk:
            # Actualizar datos del partido, preservar resultado
            for p in estado:
                if p["game_pk"] == pk:
                    for k, v in entry.items():
                        if k not in ("resultado", "marcador", "ganador"):
                            p[k] = v
                    break
            actualizados += 1
        else:
            estado.append(entry)
            nuevos += 1

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    logger.info(f"Estado LMB: {nuevos} nuevos, {actualizados} actualizados")





def actualizar_estado_resultado(game_pk: int, resultado: str, ganador: str):
    """Marca un partido como resuelto en el JSON de estado."""
    estado = cargar_estado()
    for p in estado:
        if p["game_pk"] == game_pk:
            p["resultado"] = resultado
            p["ganador"]   = ganador
            break
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# ESTADÍSTICAS DEL CSV (para el resumen semanal)
# ─────────────────────────────────────────────────────────────────────────────
def obtener_partidos_hoy_con_mercado() -> list[dict]:
    """
    Lee el CSV y retorna partidos de HOY que cumplan:
      - probabilidad_inicial >= PROB_MINIMA_SEÑAL  O  es_valor == 'SI'
      - prob_mercado distinto de N/D (tiene odds reales)
    Deduplica por (equipo_visitante, equipo_local).
    Ordenados por probabilidad_inicial descendente.
    Sirve como fuente de verdad para la sección 'Partidos de hoy'
    del mensaje de Telegram, usando datos acumulados del CSV en lugar
    de solo el run actual (robusto ante caídas de la Odds API).
    """
    from datetime import date as _date
    hoy   = _date.today().strftime("%Y-%m-%d")
    filas = _leer_todas()

    resultado = []
    vistos: set = set()

    for f in filas:
        # Solo partidos de hoy
        if f.get("fecha_hora", "")[:10] != hoy:
            continue
        # Debe tener prob_mercado válida
        pm = f.get("prob_mercado", "N/D").strip()
        if not pm or pm == "N/D":
            continue
        # Parsear probabilidad_inicial
        try:
            prob = float(f.get("probabilidad_inicial", "0").replace("%", "").strip())
        except (ValueError, AttributeError):
            continue
        # Debe cumplir umbral mínimo O ser valor confirmado
        es_valor = f.get("es_valor", "NO").strip().upper() == "SI"
        if not es_valor and prob < config.PROB_MINIMA_SEÑAL:
            continue
        # Deduplicar por (visitante, local)
        clave = (
            f.get("equipo_visitante", "").strip().lower(),
            f.get("equipo_local", "").strip().lower(),
        )
        if clave in vistos:
            continue
        vistos.add(clave)
        resultado.append(f)

    # Ordenar por probabilidad descendente
    resultado.sort(
        key=lambda x: float(
            x.get("probabilidad_inicial", "0%").replace("%", "").strip() or 0
        ),
        reverse=True,
    )
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# ESTADÍSTICAS DEL CSV (para el resumen semanal)
# ─────────────────────────────────────────────────────────────────────────────
def obtener_estadisticas(liga: str = None) -> dict:
    """
    Lee el CSV completo y calcula estadísticas de rendimiento del bot.
    Si liga es 'MLB', 'LMB' o None (todas), filtra según corresponda.
    Incluye métricas globales, de selecciones destacadas (prob ≥ PROB_MINIMA_ANALISIS)
    y de señales de valor.
    """
    filas = _leer_todas()
    if liga in ("MLB", "LMB"):
        filas = [f for f in filas if (f.get("liga", "MLB") or "MLB").strip() == liga]
    total      = len(filas)
    acertados  = sum(1 for f in filas if f.get("resultado") == "acertado")
    fallidos   = sum(1 for f in filas if f.get("resultado") == "fallido")
    pendientes = sum(1 for f in filas if f.get("resultado") == "pendiente")
    valor      = sum(1 for f in filas if f.get("es_valor") == "SI")
    valor_ok   = sum(1 for f in filas if f.get("es_valor") == "SI"
                     and f.get("resultado") == "acertado")

    # ── SELECCIONES DESTACADAS (probabilidad_inicial >= PROB_MINIMA_ANALISIS) ──
    def _es_destacado(f):
        try:
            prob = float(f.get("probabilidad_inicial", "0").replace("%", "").strip())
            return prob >= config.PROB_MINIMA_ANALISIS
        except (ValueError, AttributeError):
            return False

    rec_total      = sum(1 for f in filas if _es_destacado(f))
    rec_acertados  = sum(1 for f in filas if _es_destacado(f) and f.get("resultado") == "acertado")
    rec_fallidos   = sum(1 for f in filas if _es_destacado(f) and f.get("resultado") == "fallido")
    rec_pendientes = sum(1 for f in filas if _es_destacado(f) and f.get("resultado") == "pendiente")

    # ── CONFIANZA MEDIA (prob >= PROB_MINIMA_ANALISIS pero edge < EDGE_MINIMO) ──
    def _es_confianza_media(f):
        try:
            prob = float(f.get("probabilidad_inicial", "0").replace("%", "").strip())
            if prob < config.PROB_MINIMA_ANALISIS:
                return False
            pm_str = f.get("prob_mercado", "N/D").strip()
            if pm_str != "N/D":
                pm = float(pm_str.replace("%", "").strip())
                edge = prob - pm
                if edge >= config.EDGE_MINIMO:
                    return False
            return True
        except (ValueError, AttributeError):
            return False

    media_total      = sum(1 for f in filas if _es_confianza_media(f))
    media_acertados  = sum(1 for f in filas if _es_confianza_media(f) and f.get("resultado") == "acertado")
    media_fallidos   = sum(1 for f in filas if _es_confianza_media(f) and f.get("resultado") == "fallido")
    media_pendientes = sum(1 for f in filas if _es_confianza_media(f) and f.get("resultado") == "pendiente")

    # ── CONFIANZA ALTA (prob >= PROB_MINIMA_ANALISIS y edge >= EDGE_MINIMO) ──
    def _es_confianza_alta(f):
        try:
            prob = float(f.get("probabilidad_inicial", "0").replace("%", "").strip())
            if prob < config.PROB_MINIMA_ANALISIS:
                return False
            pm_str = f.get("prob_mercado", "N/D").strip()
            if pm_str == "N/D":
                return False
            pm = float(pm_str.replace("%", "").strip())
            edge = prob - pm
            return edge >= config.EDGE_MINIMO
        except (ValueError, AttributeError):
            return False

    alta_total      = sum(1 for f in filas if _es_confianza_alta(f))
    alta_acertados  = sum(1 for f in filas if _es_confianza_alta(f) and f.get("resultado") == "acertado")
    alta_fallidos   = sum(1 for f in filas if _es_confianza_alta(f) and f.get("resultado") == "fallido")
    alta_pendientes = sum(1 for f in filas if _es_confianza_alta(f) and f.get("resultado") == "pendiente")

    # ── SOLO INFORMATIVOS (prob < PROB_MINIMA_ANALISIS) ──
    def _es_informativo(f):
        try:
            prob = float(f.get("probabilidad_inicial", "0").replace("%", "").strip())
            return prob < config.PROB_MINIMA_ANALISIS
        except (ValueError, AttributeError):
            return False

    baja_total      = sum(1 for f in filas if _es_informativo(f))
    baja_acertados  = sum(1 for f in filas if _es_informativo(f) and f.get("resultado") == "acertado")
    baja_fallidos   = sum(1 for f in filas if _es_informativo(f) and f.get("resultado") == "fallido")
    baja_pendientes = sum(1 for f in filas if _es_informativo(f) and f.get("resultado") == "pendiente")

    win_rate = (acertados / (acertados + fallidos) * 100
                if (acertados + fallidos) > 0 else 0)
    valor_rate = (valor_ok / valor * 100 if valor > 0 else 0)
    rec_win_rate = (rec_acertados / (rec_acertados + rec_fallidos) * 100
                    if (rec_acertados + rec_fallidos) > 0 else 0)
    media_win_rate = (media_acertados / (media_acertados + media_fallidos) * 100
                      if (media_acertados + media_fallidos) > 0 else 0)
    alta_win_rate = (alta_acertados / (alta_acertados + alta_fallidos) * 100
                     if (alta_acertados + alta_fallidos) > 0 else 0)
    baja_win_rate = (baja_acertados / (baja_acertados + baja_fallidos) * 100
                     if (baja_acertados + baja_fallidos) > 0 else 0)

    return {
        "total":       total,
        "acertados":   acertados,
        "fallidos":    fallidos,
        "pendientes":  pendientes,
        "win_rate":    round(win_rate, 1),
        "valor_total": valor,
        "valor_ok":    valor_ok,
        "valor_rate":  round(valor_rate, 1),
        # Selecciones destacadas (prob ≥ PROB_MINIMA_ANALISIS)
        "rec_total":       rec_total,
        "rec_acertados":   rec_acertados,
        "rec_fallidos":    rec_fallidos,
        "rec_pendientes":  rec_pendientes,
        "rec_win_rate":    round(rec_win_rate, 1),
        # Confianza Media (prob ≥ PROB_MINIMA_APUESTA pero edge < EDGE_MINIMO)
        "media_total":       media_total,
        "media_acertados":   media_acertados,
        "media_fallidos":    media_fallidos,
        "media_pendientes":  media_pendientes,
        "media_win_rate":    round(media_win_rate, 1),
        # Confianza Alta (prob ≥ PROB_MINIMA_APUESTA y edge ≥ EDGE_MINIMO)
        "alta_total":       alta_total,
        "alta_acertados":   alta_acertados,
        "alta_fallidos":    alta_fallidos,
        "alta_pendientes":  alta_pendientes,
        "alta_win_rate":    round(alta_win_rate, 1),
        # Solo Informativos (prob < PROB_MINIMA_APUESTA)
        "baja_total":       baja_total,
        "baja_acertados":   baja_acertados,
        "baja_fallidos":    baja_fallidos,
        "baja_pendientes":  baja_pendientes,
        "baja_win_rate":    round(baja_win_rate, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS PRIVADOS
# ─────────────────────────────────────────────────────────────────────────────
def _leer_ids_existentes() -> set:
    if not os.path.exists(config.CSV_PATH):
        return set()
    ids = set()
    with open(config.CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ids.add(row.get("id_partido", ""))
    return ids


def _leer_todas() -> list[dict]:
    if not os.path.exists(config.CSV_PATH):
        return []
    with open(config.CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _escribir_todas(filas: list[dict]):
    with open(config.CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNAS)
        w.writeheader()
        w.writerows(filas)


def _generar_descripcion(a: GameAnalysis) -> str:
    """Genera un texto-resumen del análisis para la columna descripción."""
    away_p = a.away_pitcher
    home_p = a.home_pitcher
    lines  = [
        f"Favorito: {a.favorito} ({a.prob_favorito:.1f}%)",
        f"Pitcheo: {a.away_team} FIP={away_p.fip:.2f}/xFIP={away_p.xfip:.2f} | "
        f"{a.home_team} FIP={home_p.fip:.2f}/xFIP={home_p.xfip:.2f}",
        f"wRC+: {a.away_team}={a.away_offense.wrc_plus:.0f} | "
        f"{a.home_team}={a.home_offense.wrc_plus:.0f}",
        f"Bullpen WAR: {a.away_team}={a.away_bullpen.war_bullpen:.2f} | "
        f"{a.home_team}={a.home_bullpen.war_bullpen:.2f}",
        f"Riesgo: {a.factor_riesgo}",
    ]
    if a.es_valor:
        lines.append(
            f"VALOR ⭐ — Mercado paga {a.odds_mercado:.1f}% "
            f"vs sabermetría {a.prob_favorito:.1f}%"
        )
    return " || ".join(lines)
