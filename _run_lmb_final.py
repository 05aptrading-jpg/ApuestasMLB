import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.LMB_ACTIVO = True
import data_manager as dm
dm.inicializar_csv()
from analyzer_lmb import analizar_lmb_dia

results = analizar_lmb_dia("2026-05-31")
print(f"Total: {len(results)}")
for r in results:
    print(f"  {r['away_team']} @ {r['home_team']} -> {r['favorito']} ({r['prob_favorito']:.1f}%)")

dm.guardar_analisis_lmb(results)
dm.guardar_estado_lmb(results)
print("CSV + state actualizados")

# Generate and check HTML
from miniapp_publisher import generar_html
html = generar_html()
open("index.html", "w", encoding="utf-8").write(html)
print(f"index.html generado: {len(html)} bytes")
