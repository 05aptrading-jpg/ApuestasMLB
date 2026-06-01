import json, re
html = open("index.html", "r", encoding="utf-8").read()
m = re.search(r"const DATA = ({.*?});\s*$", html, re.MULTILINE | re.DOTALL)
d = json.loads(m.group(1))
today = [g for g in d["games"] if g.get("game_date") == "2026-05-31"]
lmb_today = [g for g in today if g.get("liga") == "LMB"]
mlb_today = [g for g in today if g.get("liga") != "LMB"]
print(f"Hoy: {len(today)} total ({len(mlb_today)} MLB + {len(lmb_today)} LMB)")
print("\nLMB:")
for g in lmb_today:
    print(f"  {g.get('status_emoji','')} {g.get('fav_team','')} vs {g.get('opp_team','')} [{g.get('state','')}] result={g.get('result','')}")
