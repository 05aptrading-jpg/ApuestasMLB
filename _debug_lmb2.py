import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.LMB_ACTIVO = True
import data_manager as dm
dm.inicializar_csv()
from analyzer_lmb import analizar_lmb_dia

# Patch to debug per game
import analyzer_lmb as al
original_fn = al.analizar_lmb_dia

def debug_analyze(fecha=None):
    from datetime import date as _date
    from api_client_lmb import mlb_lmb as lmb_client
    if not fecha:
        fecha = _date.today().strftime("%Y-%m-%d")
    parts = fecha.split("-")
    api_date = f"{parts[1]}/{parts[2]}/{parts[0]}"
    schedule = lmb_client.get_real_schedule(api_date)
    all_stats = lmb_client.get_all_team_stats()
    lg_avg = al._compute_league_averages(all_stats)
    form_data = lmb_client.get_team_form(fecha)
    pitcher_db = lmb_client.get_individual_pitcher_stats()
    
    analyses = []
    for i, game in enumerate(schedule):
        away_api = game["away_team"]
        home_api = game["home_team"]
        try:
            away_br = al._normalize_team(away_api)
            home_br = al._normalize_team(home_api)
            away_b, away_p, away_r = al._get_stats_for_team(away_br, all_stats)
            home_b, home_p, home_r = al._get_stats_for_team(home_br, all_stats)
            print(f"  [{i+1}] {away_api} @ {home_api}: away_p={type(away_p).__name__} away_b={type(away_b).__name__} away_r={type(away_r).__name__}")
        except Exception as e:
            print(f"  [{i+1}] {away_api} @ {home_api}: ERROR in stats: {e}")
            continue
    
    print("\n--- Running full analysis ---")
    results = analizar_lmb_dia(fecha)
    print(f"Total results: {len(results)}")
    return results

results = debug_analyze("2026-05-31")
for r in results:
    print(f"  {r['away_team']} @ {r['home_team']} -> {r['favorito']} ({r['prob_favorito']:.1f}%)")

dm.guardar_analisis_lmb(results)
dm.guardar_estado_lmb(results)
print("CSV + state actualizados")
