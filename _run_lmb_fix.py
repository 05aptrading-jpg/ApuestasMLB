import sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.LMB_ACTIVO = True
import data_manager as dm
dm.inicializar_csv()

from api_client_lmb import mlb_lmb as lmb_client
from analyzer_lmb import (
    _normalize_team, _get_stats_for_team, _compute_league_averages,
    _calcular_bloque1, _calcular_bloque2, _calcular_bloque3, _calcular_bloque4,
    _form_to_score, _generar_descripcion_lmb, _safe_float,
    _compute_team_fip, _compute_team_wrc, _score_fip, _score_kbb, _score_wrc,
    _compute_pitcher_fip,
)
from analyzer import calcular_trigger
from datetime import date

fecha = "2026-05-31"
parts = fecha.split("-")
api_date = f"{parts[1]}/{parts[2]}/{parts[0]}"
schedule = lmb_client.get_real_schedule(api_date)
all_stats = lmb_client.get_all_team_stats()
lg_avg = _compute_league_averages(all_stats)
form_data = lmb_client.get_team_form(fecha)
pitcher_db = lmb_client.get_individual_pitcher_stats()

w1 = config.PESO_LMB_PITCHEO / 100.0
w2 = config.PESO_LMB_OFENSIVA / 100.0
w3 = config.PESO_LMB_BULLPEN / 100.0
w4 = config.PESO_LMB_EFICIENCIA / 100.0
w5 = config.PESO_LMB_FORMA / 100.0

results = []
for i, game in enumerate(schedule):
    away_api = game["away_team"]
    home_api = game["home_team"]
    try:
        away_br = _normalize_team(away_api)
        home_br = _normalize_team(home_api)
        away_b, away_p, away_r = _get_stats_for_team(away_br, all_stats)
        home_b, home_p, home_r = _get_stats_for_team(home_br, all_stats)
        
        s1a = _calcular_bloque1(away_p)
        s1h = _calcular_bloque1(home_p)
        s2a = _calcular_bloque2(away_b)
        s2h = _calcular_bloque2(home_b)
        s3a = _calcular_bloque3(away_p)
        s3h = _calcular_bloque3(home_p)
        s4a = _calcular_bloque4(away_r)
        s4h = _calcular_bloque4(home_r)

        s5a = 50.0
        s5h = 50.0
        fd_a = (form_data or {}).get(away_api, {})
        fd_h = (form_data or {}).get(home_api, {})
        if fd_a:
            s5a = _form_to_score(fd_a.get("wins", 0))
        if fd_h:
            s5h = _form_to_score(fd_h.get("wins", 0))
        s5 = (s5a + s5h) / 2

        total_away_raw = s1a * w1 + s2a * w2 + s3a * w3 + s4a * w4 + s5 * w5
        total_home_raw = s1h * w1 + s2h * w2 + s3h * w3 + s4h * w4 + s5 * w5
        
        print(f"  [{i+1}] {away_api} @ {home_api}: raw_away={total_away_raw:.1f} raw_home={total_home_raw:.1f}")
        
        if total_away_raw < 50 and total_home_raw < 50:
            print(f"       SKIPPED: both < 50")
            continue

        abridor_a = game.get("away_pitcher_name") or "?"
        abridor_h = game.get("home_pitcher_name") or "?"
        pa_data = pitcher_db.get(abridor_a) if abridor_a != "?" else None
        ph_data = pitcher_db.get(abridor_h) if abridor_h != "?" else None
        
        if pa_data:
            fip_a = _compute_pitcher_fip(pa_data, lg_avg["cFIP"])
            kbb_a = pa_data.get("kbb") or _safe_float((away_p or {}).get("SO/W"))
        elif away_p:
            fip_a = _compute_team_fip(away_p, lg_avg["cFIP"])
            kbb_a = _safe_float(away_p.get("SO/W"))
        else:
            fip_a = lg_avg["cFIP"]
            kbb_a = 0
        if ph_data:
            fip_h = _compute_pitcher_fip(ph_data, lg_avg["cFIP"])
            kbb_h = ph_data.get("kbb") or _safe_float((home_p or {}).get("SO/W"))
        elif home_p:
            fip_h = _compute_team_fip(home_p, lg_avg["cFIP"])
            kbb_h = _safe_float(home_p.get("SO/W"))
        else:
            fip_h = lg_avg["cFIP"]
            kbb_h = 0
        wrc_a = _compute_team_wrc(away_b, lg_avg) if away_b else 100
        wrc_h = _compute_team_wrc(home_b, lg_avg) if home_b else 100

        s_fip_a = _score_fip(fip_a)
        s_fip_h = _score_fip(fip_h)
        s_kbb_a = _score_kbb(kbb_a)
        s_kbb_h = _score_kbb(kbb_h)
        s_wrc_a = _score_wrc(wrc_a)
        s_wrc_h = _score_wrc(wrc_h)

        s1a_enr = s1a * 0.50 + s_fip_a * 0.30 + s_kbb_a * 0.20
        s1h_enr = s1h * 0.50 + s_fip_h * 0.30 + s_kbb_h * 0.20
        s2a_enr = s2a * 0.70 + s_wrc_a * 0.30
        s2h_enr = s2h * 0.70 + s_wrc_h * 0.30

        total_away = s1a_enr * w1 + s2a_enr * w2 + s3a * w3 + s4a * w4 + s5 * w5
        total_home = s1h_enr * w1 + s2h_enr * w2 + s3h * w3 + s4h * w4 + s5 * w5

        diff = total_away - total_home
        prob_away = 50 + diff * 0.8
        prob_home = 100 - prob_away
        prob_away = max(10, min(90, prob_away))
        prob_home = max(10, min(90, prob_home))

        favorito = away_api if prob_away > prob_home else home_api
        prob_fav = prob_away if prob_away > prob_home else prob_home

        results.append({
            "game_pk": game["game_pk"],
            "game_date": fecha,
            "game_time": "",
            "away_team": away_api,
            "home_team": home_api,
            "away_pitcher": abridor_a,
            "home_pitcher": abridor_h,
            "favorito": favorito,
            "prob_favorito": round(prob_fav, 1),
            "odds_mercado": None,
            "es_valor": False,
            "factor_riesgo": "Medio",
            "score_b1_away": round(s1a, 1),
            "score_b1_home": round(s1h, 1),
            "score_b2_away": round(s2a, 1),
            "score_b2_home": round(s2h, 1),
            "score_b3_away": round(s3a, 1),
            "score_b3_home": round(s3h, 1),
            "score_b4_away": round(s4a, 1),
            "score_b4_home": round(s4h, 1),
            "fip_away": round(fip_a, 2),
            "fip_home": round(fip_h, 2),
            "xfip_away": round(fip_a, 2),
            "xfip_home": round(fip_h, 2),
            "kbb_away": round(kbb_a, 2),
            "kbb_home": round(kbb_h, 2),
            "wrc_away": wrc_a,
            "wrc_home": wrc_h,
            "war_bullpen_away": None,
            "war_bullpen_home": None,
            "senal_moneyline": "NO APOSTAR",
            "nivel_certidumbre": "",
            "descripcion": "",
        })
        print(f"       OK: {favorito} ({prob_fav:.1f}%)")
    except Exception as e:
        print(f"       ERROR: {e}")
        traceback.print_exc()

print(f"\nTotal: {len(results)} de 10")
dm.guardar_analisis_lmb(results)
dm.guardar_estado_lmb(results)
print("CSV + state actualizados")
