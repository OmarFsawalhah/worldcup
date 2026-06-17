"""Fetch player thumbnail URLs from Wikipedia and save them to players.photo_url.

Usage:
    python scripts/fetch_player_photos.py              # fill missing photos only
    python scripts/fetch_player_photos.py --refresh    # overwrite all photos
    python scripts/fetch_player_photos.py --team BRA   # one team only (by team.code)

Notes:
- Hits Wikipedia REST API: https://en.wikipedia.org/api/rest_v1/page/summary/<title>
- Rate-limited to ~1 req/sec to stay polite (Wikipedia asks for <200 req/s; we go
  way under that).
- Falls back from "<Name> (footballer, born YYYY)" → "<Name>" → "<Name> <Country>".
- Saves the originalimage URL when available, else thumbnail URL. None of these
  URLs are guaranteed forever — Wikipedia images can move. Run this script again
  later to refresh.
"""
import argparse
import os
import sys
import time
import re

# Allow `python scripts/fetch_player_photos.py` from project root
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# Fix UTF-8 on Windows console
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

from app import app
from models import db, Player, Team


WIKI_BASE = "https://en.wikipedia.org/api/rest_v1/page/summary"
HEADERS = {
    "User-Agent": "WC2026Predictor/1.0 (https://github.com/OmarFsawalhah/worldcup) PlayerPhotoFetch",
    "Accept": "application/json",
}
SLEEP_BETWEEN = 0.8  # seconds — ~1.25 req/sec, polite


def _slug(name: str) -> str:
    """Wikipedia title casing — capitalize words, replace spaces with underscores
    is done by the REST API automatically; we just URL-quote."""
    return name.strip().replace(" ", "_")


def _fetch_summary(title: str) -> dict | None:
    """Returns the JSON dict for a Wikipedia page summary, or None on 404."""
    url = f"{WIKI_BASE}/{_slug(title)}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
    except requests.RequestException:
        return None
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def _photo_url_from_summary(summary: dict) -> str | None:
    """Extract a clean photo URL from a Wikipedia summary."""
    if not summary:
        return None
    # Prefer the higher-res 'originalimage', fall back to 'thumbnail'
    src = (summary.get("originalimage") or {}).get("source") \
        or (summary.get("thumbnail") or {}).get("source")
    if not src:
        return None
    # Skip generic placeholder / logo / SVG flags
    if any(x in src.lower() for x in ("flag_of_", "default_avatar", "no_image", "soccerball")):
        return None
    return src


def _looks_like_footballer(summary: dict, country_hint: str = "") -> bool:
    """Heuristic — verify the Wikipedia hit is actually about a footballer.
    Looks at the page description and extract for sport keywords."""
    if not summary:
        return False
    desc = (summary.get("description") or "").lower()
    extract = (summary.get("extract") or "").lower()
    keywords = ("footballer", "football player", "soccer player", "midfielder",
                "forward", "striker", "defender", "goalkeeper")
    return any(k in desc or k in extract for k in keywords)


def try_titles_for_player(name_en: str, country_en: str) -> str | None:
    """Try several Wikipedia title variants. Return the best photo URL or None."""
    name = re.sub(r"\s+", " ", name_en).strip()
    # 1. "Player Name (footballer)"
    candidates = [
        f"{name} (footballer)",
        f"{name} (soccer)",
        f"{name} ({country_en} footballer)" if country_en else None,
        name,
    ]
    candidates = [c for c in candidates if c]

    for title in candidates:
        summary = _fetch_summary(title)
        time.sleep(SLEEP_BETWEEN)
        if not summary:
            continue
        # If the title is just the name (no disambiguator), accept only if the
        # page clearly looks like a footballer — otherwise we'll pick up a
        # historical person or actor with the same name.
        if title == name and not _looks_like_footballer(summary, country_en):
            continue
        url = _photo_url_from_summary(summary)
        if url:
            return url
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                        help="Overwrite existing photo_url values (default: skip players who already have one).")
    parser.add_argument("--team", type=str, default=None,
                        help="Only process one team (by team.code, e.g. USA, BRA).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N players (useful for a dry run).")
    parser.add_argument("--placeholder-only", action="store_true",
                        help="Only process players whose name starts with the team name "
                             "(generic placeholders like 'Brazil #14') — usually skip these.")
    args = parser.parse_args()

    with app.app_context():
        q = Player.query.join(Team, Player.team_id == Team.id)
        if args.team:
            q = q.filter(Team.code == args.team.upper())
        if not args.refresh:
            q = q.filter((Player.photo_url.is_(None)) | (Player.photo_url == ""))
        if not args.placeholder_only:
            # Skip generic placeholders (e.g. "Brazil #14") — they will never match Wikipedia
            q = q.filter(~Player.name_en.like("%#%"))

        players = q.all()
        if args.limit:
            players = players[: args.limit]

        print(f"Players to process: {len(players)}")
        if not players:
            return

        found, missed = 0, 0
        for i, p in enumerate(players, 1):
            team = p.team
            country = team.name_en if team else ""
            print(f"[{i}/{len(players)}] {p.name_en} ({country}) ...", end=" ", flush=True)
            url = try_titles_for_player(p.name_en, country)
            if url:
                p.photo_url = url
                db.session.commit()
                found += 1
                print("OK")
            else:
                missed += 1
                print("no photo")

        print(f"\nDone. Found {found}, missed {missed}.")


if __name__ == "__main__":
    main()
