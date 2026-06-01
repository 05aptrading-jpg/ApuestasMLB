import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
config.LMB_ACTIVO = True

import data_manager as dm
dm.inicializar_csv()

from analyzer_lmb import analizar_lmb_dia
results = analizar_lmb_dia()
print(f"Analizados: {len(results)} partidos")
for r in results:
    away = r.get("away_team", "?")
    home = r.get("home_team", "?")
    fav = r.get("favorito", "?")
    prob = r.get("prob_favorito", 0)
    print(f"  {away} @ {home} -> {fav} ({prob:.1f}%)")

dm.guardar_analisis_lmb(results)
dm.guardar_estado_lmb(results)
print("Estado y CSV actualizados")

from miniapp_publisher import publicar
ok = publicar()
print("Mini App publicada" if ok else "Fallo al publicar")
