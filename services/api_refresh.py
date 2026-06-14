"""Live refresh from football-data.org — called from the admin UI.

Only updates match `status`. Scores are also pulled, but only written if
the admin hasn't manually entered a result yet (i.e. home_score is NULL),
so admin overrides are never clobbered.
"""
import os
import time

import requests

from models import db, Match, Team

API_BASE = "https://api.football-data.org/v4"
COMPETITION = "WC"

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


def refresh_match_statuses():
    """Returns a dict: {'updated_status': N, 'updated_score': M, 'skipped': K}."""
    key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if not key:
        raise RuntimeError("FOOTBALL_DATA_API_KEY is not set.")

    headers = {"X-Auth-Token": key}
    r = requests.get(f"{API_BASE}/competitions/{COMPETITION}/matches",
                     headers=headers, timeout=20)
    if r.status_code == 429:
        wait = int(r.headers.get("X-RequestCounter-Reset", 60))
        time.sleep(wait + 1)
        r = requests.get(f"{API_BASE}/competitions/{COMPETITION}/matches",
                         headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json().get("matches", [])

    # Build code -> team_id lookup
    code_to_team_id = {t.code: t.id for t in Team.query.all()}

    updated_status = 0
    updated_score = 0
    skipped = 0
    for m_api in data:
        home_name = m_api.get("homeTeam", {}).get("tla") or ""
        away_name = m_api.get("awayTeam", {}).get("tla") or ""
        home_id = code_to_team_id.get(home_name.upper())
        away_id = code_to_team_id.get(away_name.upper())
        if not home_id or not away_id:
            skipped += 1
            continue

        # Match local rows by team pairing — tolerant of date drift on the API side
        m_local = Match.query.filter_by(home_team_id=home_id, away_team_id=away_id).first()
        if not m_local:
            skipped += 1
            continue

        new_status = STATUS_MAP.get(m_api.get("status"), "upcoming")
        if m_local.status != new_status:
            m_local.status = new_status
            updated_status += 1

        # Only sync scores if admin hasn't manually entered them
        if m_local.home_score is None:
            ft = (m_api.get("score") or {}).get("fullTime", {}) or {}
            api_h = ft.get("home")
            api_a = ft.get("away")
            if api_h is not None and api_a is not None:
                m_local.home_score = api_h
                m_local.away_score = api_a
                updated_score += 1

    db.session.commit()
    return {"updated_status": updated_status,
            "updated_score": updated_score,
            "skipped": skipped}
