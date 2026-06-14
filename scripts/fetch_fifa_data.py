"""Refresh teams / fixtures / squads from football-data.org.

Requires FOOTBALL_DATA_API_KEY in environment (or .env file).
Get a free key at: https://www.football-data.org/client/register

Free-tier rate limit: 10 requests per minute. Fetching 48 squads takes ~5 min.

Usage:
    python scripts/fetch_fifa_data.py                # full refresh
    python scripts/fetch_fifa_data.py --skip-squads  # teams + fixtures only (fast)
    python scripts/fetch_fifa_data.py --dry-run      # show what would happen
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"

load_dotenv(ROOT / ".env")

API_BASE = "https://api.football-data.org/v4"
COMPETITION = "WC"  # FIFA World Cup

# Map football-data.org statuses -> our internal statuses
STATUS_MAP = {
    "SCHEDULED": "upcoming",
    "TIMED": "upcoming",
    "POSTPONED": "upcoming",
    "IN_PLAY": "live",
    "LIVE": "live",
    "PAUSED": "live",
    "FINISHED": "finished",
    "AWARDED": "finished",
    "SUSPENDED": "upcoming",
    "CANCELLED": "upcoming",
}

# Baseline Arabic names keyed by football-data.org's 3-letter TLA codes.
# Also augmented at runtime from existing data/teams.json so manual edits stick.
ARABIC_NAMES = {
    "ARG": "الأرجنتين", "BRA": "البرازيل", "FRA": "فرنسا", "ESP": "إسبانيا",
    "POR": "البرتغال", "GER": "ألمانيا", "ENG": "إنجلترا", "NED": "هولندا",
    "ITA": "إيطاليا", "BEL": "بلجيكا", "CRO": "كرواتيا", "SUI": "سويسرا",
    "DEN": "الدنمارك", "URY": "الأوروغواي", "URU": "الأوروغواي",
    "MEX": "المكسيك", "USA": "الولايات المتحدة", "CAN": "كندا",
    "JPN": "اليابان", "KOR": "كوريا الجنوبية", "AUS": "أستراليا",
    "MAR": "المغرب", "EGY": "مصر", "TUN": "تونس", "ALG": "الجزائر",
    "SEN": "السنغال", "GHA": "غانا", "CIV": "ساحل العاج", "RSA": "جنوب أفريقيا",
    "QAT": "قطر", "KSA": "السعودية", "IRN": "إيران", "JOR": "الأردن",
    "UZB": "أوزبكستان", "TUR": "تركيا", "NOR": "النرويج", "AUT": "النمسا",
    "SCO": "اسكتلندا", "WAL": "ويلز", "UKR": "أوكرانيا", "PAR": "الباراغواي",
    "ECU": "الإكوادور", "COL": "كولومبيا", "JAM": "جامايكا", "PAN": "بنما",
    "CRC": "كوستاريكا", "NZL": "نيوزيلندا", "POL": "بولندا", "SRB": "صربيا",
    "SWE": "السويد", "CZE": "التشيك", "HAI": "هايتي", "BIH": "البوسنة والهرسك",
    "CPV": "الرأس الأخضر", "COD": "جمهورية الكونغو الديمقراطية",
    "IRQ": "العراق", "CUW": "كوراساو",
}


def _headers():
    key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if not key or key == "your_key_here":
        sys.exit("FOOTBALL_DATA_API_KEY not set. Copy .env.example to .env and add your key.")
    return {"X-Auth-Token": key}


def _get(path, throttle=True, _attempt=1):
    url = f"{API_BASE}{path}"
    print(f"  GET {url}")
    try:
        r = requests.get(url, headers=_headers(), timeout=30)
    except (requests.ConnectionError, requests.Timeout) as e:
        if _attempt >= 4:
            raise
        backoff = 5 * _attempt
        print(f"  Network error ({e.__class__.__name__}); retry {_attempt}/3 in {backoff}s")
        time.sleep(backoff)
        return _get(path, throttle=throttle, _attempt=_attempt + 1)
    if r.status_code == 429:
        wait = int(r.headers.get("X-RequestCounter-Reset", 60))
        print(f"  Rate-limited; sleeping {wait}s")
        time.sleep(wait + 1)
        return _get(path, throttle=False)
    r.raise_for_status()
    if throttle:
        # 10 req/min on free tier -> ~7s safe headroom
        time.sleep(7)
    return r.json()


def _flag_for(code):
    """Convert a 3-letter country code into a flag emoji.
    football-data.org uses 3-letter codes; flag emojis use 2-letter ISO 3166-1 alpha-2."""
    alpha2 = {
        "ARG": "AR", "BRA": "BR", "FRA": "FR", "ESP": "ES", "POR": "PT", "GER": "DE",
        "ENG": "GB", "NED": "NL", "ITA": "IT", "BEL": "BE", "CRO": "HR", "SUI": "CH",
        "DEN": "DK", "POL": "PL", "SRB": "RS", "URU": "UY", "URY": "UY",
        "MEX": "MX", "USA": "US", "CAN": "CA", "JPN": "JP", "KOR": "KR", "AUS": "AU",
        "MAR": "MA", "EGY": "EG", "TUN": "TN", "ALG": "DZ", "SEN": "SN", "GHA": "GH",
        "CIV": "CI", "RSA": "ZA", "QAT": "QA", "KSA": "SA", "IRN": "IR", "JOR": "JO",
        "UZB": "UZ", "TUR": "TR", "NOR": "NO", "AUT": "AT", "SCO": "GB", "WAL": "GB",
        "UKR": "UA", "PAR": "PY", "ECU": "EC", "COL": "CO", "JAM": "JM", "PAN": "PA",
        "CRC": "CR", "NZL": "NZ", "IRL": "IE", "ROU": "RO", "CZE": "CZ", "SVK": "SK",
        "HUN": "HU", "GRE": "GR", "NGA": "NG", "CMR": "CM", "MLI": "ML", "BFA": "BF",
        # Extra 2026 entrants
        "SWE": "SE", "HAI": "HT", "BIH": "BA", "CPV": "CV", "COD": "CD",
        "IRQ": "IQ", "CUW": "CW",
    }.get(code.upper())
    if not alpha2:
        return "🏳️"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in alpha2)


# Code aliases — when football-data.org uses one code and our Arabic
# translation dict uses another, map them so we keep the Arabic name.
CODE_ALIASES = {"URY": "URU"}


def fetch_teams():
    print("Fetching competition teams...")
    data = _get(f"/competitions/{COMPETITION}/teams")
    teams = []
    for t in data.get("teams", []):
        code = (t.get("tla") or t.get("shortName") or t.get("name", ""))[:3].upper()
        teams.append({
            "id_api": t["id"],
            "code": code,
            "name_en": t.get("name") or t.get("shortName") or code,
            "name_ar": ARABIC_NAMES.get(code) or ARABIC_NAMES.get(CODE_ALIASES.get(code, "")) or t.get("name", code),
            "flag": _flag_for(code),
            "group": None,  # filled below from match data if available
        })
    return teams


def fetch_matches(teams_by_api_id):
    print("Fetching competition matches...")
    data = _get(f"/competitions/{COMPETITION}/matches")
    matches = []
    group_assignments = {}  # team_api_id -> group letter
    for m in data.get("matches", []):
        home_id = m["homeTeam"]["id"]
        away_id = m["awayTeam"]["id"]
        if home_id not in teams_by_api_id or away_id not in teams_by_api_id:
            continue
        stage = (m.get("stage") or "GROUP_STAGE").upper()
        group_raw = m.get("group")  # e.g. "GROUP_A"
        group_letter = None
        stage_internal = "group"
        if stage == "GROUP_STAGE":
            stage_internal = "group"
            if group_raw and group_raw.startswith("GROUP_"):
                group_letter = group_raw.split("_")[1]
                group_assignments[home_id] = group_letter
                group_assignments[away_id] = group_letter
        else:
            stage_internal = {
                "LAST_32": "r32",
                "ROUND_OF_32": "r32",
                "LAST_16": "r16",
                "ROUND_OF_16": "r16",
                "QUARTER_FINALS": "qf",
                "SEMI_FINALS": "sf",
                "THIRD_PLACE": "third",
                "FINAL": "final",
            }.get(stage, "group")
        score = m.get("score", {}) or {}
        ft = score.get("fullTime", {}) or {}
        matches.append({
            "id_api": m["id"],
            "home_code": teams_by_api_id[home_id]["code"],
            "away_code": teams_by_api_id[away_id]["code"],
            "kickoff_utc": m["utcDate"],
            "stage": stage_internal,
            "group_letter": group_letter,
            "venue": (m.get("venue") or "").strip() or None,
            "status": STATUS_MAP.get(m.get("status"), "upcoming"),
            "home_score": ft.get("home"),
            "away_score": ft.get("away"),
        })
    return matches, group_assignments


def fetch_squads(teams):
    """Resumable: any team already present in data/players_stars.json with
    >=11 players is skipped. We save after every team so a crash loses at
    most one team's progress."""
    out_path = DATA / "players_stars.json"
    squads = {}
    if out_path.exists():
        try:
            squads = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            squads = {}
    todo = [t for t in teams if len(squads.get(t["code"], [])) < 11]
    done = len(teams) - len(todo)
    print(f"Fetching squads: {done}/{len(teams)} already cached, {len(todo)} to go")
    for i, t in enumerate(todo, 1):
        print(f"  [{i}/{len(todo)}] {t['name_en']}")
        try:
            data = _get(f"/teams/{t['id_api']}")
        except requests.HTTPError as e:
            print(f"    skip ({e})")
            continue
        except requests.ConnectionError as e:
            print(f"    network failed after retries ({e}); saving progress and stopping")
            break
        roster = []
        for p in data.get("squad", []) or []:
            roster.append([
                p.get("name", "?"),
                p.get("name", "?"),  # name_ar — API gives English only
                (p.get("position") or "")[:16],
                p.get("shirtNumber") or 0,
            ])
        squads[t["code"]] = roster
        # Persist after every team so progress survives crashes
        out_path.write_text(json.dumps(squads, ensure_ascii=False, indent=2), encoding="utf-8")
    return squads


def _merge_arabic_names():
    """If data/teams.json already exists with Arabic translations, keep them."""
    existing = DATA / "teams.json"
    if not existing.exists():
        return
    try:
        rows = json.loads(existing.read_text(encoding="utf-8"))
        for r in rows:
            code = r["code"]
            existing_ar = r.get("name_ar", "")
            # Only accept previously-stored value if it looks Arabic and we
            # don't already have a hardcoded entry for this code.
            if code in ARABIC_NAMES:
                continue
            if any("؀" <= ch <= "ۿ" for ch in existing_ar):
                ARABIC_NAMES[code] = existing_ar
    except Exception as e:
        print(f"  (couldn't preserve Arabic names: {e})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-squads", action="store_true",
                    help="Only refresh teams and fixtures (much faster)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan, don't write files")
    args = ap.parse_args()

    _merge_arabic_names()

    if args.dry_run:
        print(f"Would call {API_BASE}/competitions/{COMPETITION}/{{teams,matches}}")
        if not args.skip_squads:
            print("Would call /teams/<id> for each team in the competition")
        return

    teams = fetch_teams()
    teams_by_api_id = {t["id_api"]: t for t in teams}
    matches, groups = fetch_matches(teams_by_api_id)

    # backfill group letters onto teams from group-stage matches
    for t in teams:
        t["group"] = groups.get(t["id_api"])

    # Write teams.json in the format seed.py expects
    teams_out = [{"code": t["code"], "name_en": t["name_en"], "name_ar": t["name_ar"],
                  "flag": t["flag"], "group": t["group"]} for t in teams]
    (DATA / "teams.json").write_text(json.dumps(teams_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(teams_out)} teams -> data/teams.json")

    # Write matches.json
    (DATA / "matches.json").write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(matches)} matches -> data/matches.json")

    if not args.skip_squads:
        squads = fetch_squads(teams)
        (DATA / "players_stars.json").write_text(json.dumps(squads, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote squads for {len(squads)} teams -> data/players_stars.json")

    print("\nDone. Now reseed:")
    print("  rm worldcup.db instance/worldcup.db   # remove old DB")
    print("  python scripts/seed.py                # load the fresh data")


if __name__ == "__main__":
    main()
