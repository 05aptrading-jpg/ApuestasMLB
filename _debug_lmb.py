import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.LMB_ACTIVO = True
from api_client_lmb import mlb_lmb as client

schedule = client.get_real_schedule("05/31/2026")
print(f"Schedule: {len(schedule)} games")
for g in schedule:
    print(f"  {g['away_team']} @ {g['home_team']} [{g['status']}]")

all_stats = client.get_all_team_stats()
print(f"\nStats available for {len(all_stats)} teams:")
for k in sorted(all_stats.keys()):
    print(f"  {k}")

import analyzer_lmb
print(f"\nNormalization check:")
for g in schedule:
    away_br = analyzer_lmb._normalize_team(g["away_team"])
    home_br = analyzer_lmb._normalize_team(g["home_team"])
    away_match = away_br in all_stats if away_br else False
    home_match = home_br in all_stats if home_br else False
    print(f"  {g['away_team']} -> '{away_br}' (found={away_match}) | {g['home_team']} -> '{home_br}' (found={home_match})")
