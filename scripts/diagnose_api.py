"""Tells you exactly what football-data.org returns for the World Cup —
specifically whether goals[] and scorer data are present in your tier.

Usage:
    set FOOTBALL_DATA_API_KEY=your_key_here
    python scripts/diagnose_api.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

KEY = os.environ.get("FOOTBALL_DATA_API_KEY")
if not KEY:
    print("ERROR: FOOTBALL_DATA_API_KEY env var not set.")
    print("On Windows PowerShell: $env:FOOTBALL_DATA_API_KEY = 'your_key'")
    sys.exit(1)

H = {"X-Auth-Token": KEY}
BASE = "https://api.football-data.org/v4"


def get(path):
    r = requests.get(f"{BASE}{path}", headers=H, timeout=20)
    print(f"  GET {path}  -> {r.status_code}")
    if r.status_code != 200:
        print(f"  body: {r.text[:300]}")
        return None
    return r.json()


print("\n=== Step 1: list WC matches ===")
data = get("/competitions/WC/matches")
if not data:
    sys.exit(1)

matches = data.get("matches", [])
print(f"  total matches returned: {len(matches)}")

finished = [m for m in matches if m.get("status") in ("FINISHED", "AWARDED")]
print(f"  finished matches: {len(finished)}")

if not finished:
    print("\nNo finished WC matches in the API. Either the tournament hasn't")
    print("started in their data, or your tier doesn't include WC live data.")
    sys.exit(0)

# Inspect the first finished match
sample = finished[0]
mid = sample["id"]
home = (sample.get("homeTeam") or {}).get("name")
away = (sample.get("awayTeam") or {}).get("name")
score = (sample.get("score") or {}).get("fullTime") or {}
print(f"\n=== Step 2: detail for match {mid}  ({home} vs {away}, "
      f"{score.get('home')}-{score.get('away')}) ===")

detail = get(f"/matches/{mid}")
if not detail:
    sys.exit(1)

goals = detail.get("goals") or []
print(f"  goals[] length: {len(goals)}")
if not goals:
    print("\n>>> No goals data in /v4/matches/<id>.")
    print(">>> This is the key finding: on your tier, football-data.org")
    print(">>> does NOT return per-goal scorer info for the WC competition.")
    print(">>> First-scorer auto-fetch can't work — must be entered manually.")
    print("\nFull detail keys returned:", list(detail.keys()))
    sys.exit(0)

print("\n>>> Goals data IS available! First-scorer auto-fetch should work.")
print("First 3 goals:")
for g in goals[:3]:
    minute = g.get("minute")
    scorer = (g.get("scorer") or {}).get("name")
    team = (g.get("team") or {}).get("name")
    print(f"  {minute}'  {scorer}  ({team})")

# Look for any 'man of the match' style field anywhere
print("\n=== Step 3: scan for MOTM / Man-of-the-Match fields ===")
flat = json.dumps(detail, ensure_ascii=False).lower()
for term in ("motm", "manofthematch", "man of the match", "playerofthematch"):
    if term in flat:
        print(f"  FOUND '{term}' in response — investigate further")
        break
else:
    print("  No MOTM-style field found anywhere. Confirmed: MOTM is NOT in")
    print("  football-data.org's data. Must always be entered manually.")
