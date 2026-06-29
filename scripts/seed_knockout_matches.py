"""Fetch WC2026 knockout matches (R32 → Final) from football-data.org and
insert any we don't already have. Safe to re-run — it skips any match
that's already in the DB by (kickoff_utc, home_team, away_team).

Round mappings (API -> our schema):
  LAST_32         -> r32
  LAST_16         -> r16
  QUARTER_FINALS  -> qf
  SEMI_FINALS     -> sf
  THIRD_PLACE     -> third
  FINAL           -> final

Knockout matches beyond R32 in the API may have home/away team TLA of
None (placeholders until previous rounds finish). For those, we still
create the Match row but leave home_team_id / away_team_id as NULL —
admin can fill them in later (or run the script again later and we'll
backfill). The dashboard only matches on stage so they'll appear in
the right section.

Usage:
    python scripts/seed_knockout_matches.py
    python scripts/seed_knockout_matches.py --dry-run
"""
import argparse
import os
import sys
from datetime import datetime, timezone

# Allow `python scripts/seed_knockout_matches.py` from project root
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests
from app import app
from models import db, Match, Team


API_BASE = "https://api.football-data.org/v4"
COMPETITION = "WC"

STAGE_MAP = {
    "LAST_32": "r32",
    "LAST_16": "r16",
    "QUARTER_FINALS": "qf",
    "SEMI_FINALS": "sf",
    "THIRD_PLACE": "third",
    "FINAL": "final",
}


def _parse_kickoff(iso: str) -> datetime:
    # API returns "2026-06-28T19:00:00Z" — naive UTC datetime in our schema
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without saving.")
    args = parser.parse_args()

    api_key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
    if not api_key:
        print("ERROR: FOOTBALL_DATA_API_KEY not set in .env")
        sys.exit(1)

    r = requests.get(
        f"{API_BASE}/competitions/{COMPETITION}/matches",
        headers={"X-Auth-Token": api_key, "Accept": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    api_matches = [m for m in data.get("matches", []) if m.get("stage") in STAGE_MAP]

    with app.app_context():
        code_to_team = {t.code: t for t in Team.query.all()}
        existing = Match.query.filter(
            Match.stage.in_(list(STAGE_MAP.values()))
        ).all()
        # Key: (kickoff_date+time, stage, home_tla_or_None, away_tla_or_None)
        existing_keys = set()
        for m in existing:
            h = m.home_team.code if m.home_team else None
            a = m.away_team.code if m.away_team else None
            existing_keys.add((m.kickoff_utc, m.stage, h, a))

        print(f"Knockout matches from API: {len(api_matches)}")
        print(f"Knockout matches already in DB: {len(existing)}")
        print()

        added = 0
        skipped = 0
        updated = 0
        for m in api_matches:
            stage = STAGE_MAP[m["stage"]]
            ko = _parse_kickoff(m["utcDate"])
            h_tla = (m.get("homeTeam") or {}).get("tla") or None
            a_tla = (m.get("awayTeam") or {}).get("tla") or None
            h_team = code_to_team.get(h_tla) if h_tla else None
            a_team = code_to_team.get(a_tla) if a_tla else None
            score = (m.get("score") or {}).get("fullTime") or {}
            h_score = score.get("home")
            a_score = score.get("away")

            if not h_team or not a_team:
                # One or both teams are still placeholders (e.g. R16 with
                # no TBD winner yet from R32). Our schema requires both
                # team_ids to be NOT NULL, so skip — we'll catch this
                # match on the next script run after the API has the
                # real teams.
                continue

            key = (ko, stage, h_team.code if h_team else None, a_team.code if a_team else None)
            if key in existing_keys:
                # Already in DB — possibly update scores if the API now has them
                if h_score is not None or a_score is not None:
                    match_in_db = next(
                        (em for em in existing
                         if em.kickoff_utc == ko
                         and em.stage == stage
                         and (em.home_team.code if em.home_team else None) == (h_team.code if h_team else None)
                         and (em.away_team.code if em.away_team else None) == (a_team.code if a_team else None)),
                        None,
                    )
                    if match_in_db and (match_in_db.home_score is None or match_in_db.home_score != h_score):
                        print(f"  update  {h_tla or '?'} vs {a_tla or '?'}  ({stage})  score={h_score}-{a_score}")
                        if not args.dry_run:
                            match_in_db.home_score = h_score
                            match_in_db.away_score = a_score
                            match_in_db.status = "finished"
                        updated += 1
                skipped += 1
                continue

            # New match — insert
            h_label = h_tla or "TBD"
            a_label = a_tla or "TBD"
            print(f"  add     {h_label} vs {a_label}  ({stage})  {ko}  score={h_score}-{a_score}")
            if not args.dry_run:
                nm = Match(
                    stage=stage,
                    group_letter=None,
                    home_team_id=h_team.id if h_team else None,
                    away_team_id=a_team.id if a_team else None,
                    kickoff_utc=ko,
                    venue=None,
                    status="finished" if h_score is not None else "upcoming",
                    home_score=h_score,
                    away_score=a_score,
                )
                db.session.add(nm)
            added += 1

        if not args.dry_run:
            db.session.commit()
        print()
        print(f"Done. Added {added}, updated {updated}, skipped {skipped} already-present.")
        if args.dry_run:
            print("(dry run — no changes saved)")


if __name__ == "__main__":
    main()
