import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

with open(config.CSV_PATH, encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

lmb_today = [r for r in rows if r.get("liga") == "LMB" and "2026-05-31" in r.get("fecha_hora", "")]
print(f"LMB rows in CSV for 2026-05-31: {len(lmb_today)}")
for r in lmb_today:
    away = r.get("equipo_visitante", "")
    home = r.get("equipo_local", "")
    res = r.get("resultado", "")
    print(f"  {away} @ {home} [{res}]")

all_lmb = [r for r in rows if r.get("liga") == "LMB"]
print(f"\nTotal LMB rows in CSV: {len(all_lmb)}")
