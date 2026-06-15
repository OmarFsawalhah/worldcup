"""Live refresh from football-data.org — called from the admin UI.

Pulls match status + scores. For finished matches we ALSO fetch the per-match
detail endpoint to extract the first goal scorer and try to map them to a
Player in our DB (best-effort fuzzy match on name).

NOTE on Man of the Match: football-data.org does NOT expose MOTM data at any
tier. Admins must enter that field manually.

Admin overrides are never clobbered:
- Scores are only written when match.home_score IS NULL
- first_scorer_id is only written when match.first_scorer_id IS NULL
"""
import os
import re
import time
import unicodedata

import requests

from models import db, Match, Team, Player

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


def _normalize_name(s: str) -> str:
    """Lowercase, strip diacritics, drop punctuation. Useful for fuzzy match."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _match_player_to_db(api_name: str, candidates: list) -> int | None:
    """Return Player.id whose name_en best matches the API scorer name.
    Strategy:
      1. Exact normalized match.
      2. Last-name match.
      3. Token-overlap (>= 2 tokens shared).
    Returns None if no confident match.
    """
    target = _normalize_name(api_name)
    if not target:
        return None
    target_tokens = set(target.split())

    # 1. Exact normalized name
    for p in candidates:
        if _normalize_name(p.name_en) == target:
            return p.id

    # 2. Last name (the LAST token of the API name) found as a token in our name
    api_last = target.split()[-1] if target else ""
    if api_last and len(api_last) >= 3:
        matches = [p for p in candidates if api_last in _normalize_name(p.name_en).split()]
        if len(matches) == 1:
            return matches[0].id

    # 3. Two or more shared tokens (each >= 3 chars)
    best = None
    best_overlap = 1
    for p in candidates:
        p_tokens = set(_normalize_name(p.name_en).split())
        overlap = len({t for t in target_tokens & p_tokens if len(t) >= 3})
        if overlap > best_overlap:
            best = p
            best_overlap = overlap
    return best.id if best else None


def _api_get(path: str, headers: dict, max_retry: int = 1):
    """GET with one retry on 429."""
    url = f"{API_BASE}{path}"
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code == 429 and max_retry > 0:
        wait = int(r.headers.get("X-RequestCounter-Reset", 60))
        time.sleep(wait + 1)
        return _api_get(path, headers, max_retry - 1)
    r.raise_for_status()
    return r.json()


def _fetch_first_scorer(api_match_id: int, home_team_id: int, away_team_id: int,
                       headers: dict) -> int | None:
    """Hit /v4/matches/<id> for this match, parse goals[], pick the earliest
    one (lowest minute), map scorer.name to a Player in our DB. Returns the
    Player.id or None."""
    try:
        data = _api_get(f"/matches/{api_match_id}", headers)
    except Exception:
        return None
    goals = data.get("goals") or []
    if not goals:
        return None
    # Sort by minute (earliest first). API may include None for unknown minute.
    goals_sorted = sorted(
        goals,
        key=lambda g: (g.get("minute") if g.get("minute") is not None else 999,
                       g.get("injuryTime") or 0),
    )
    first = goals_sorted[0]
    scorer = first.get("scorer") or {}
    scorer_name = scorer.get("name") or ""
    if not scorer_name:
        return None
    # Candidates are restricted to players from the two teams in this match.
    candidates = Player.query.filter(
        Player.team_id.in_([home_team_id, away_team_id])
    ).all()
    return _match_player_to_db(scorer_name, candidates)


def refresh_match_statuses():
    """Returns a dict:
        {'updated_status': N, 'updated_score': M, 'updated_scorer': K,
         'skipped': X}.
    """
    key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if not key:
        raise RuntimeError("FOOTBALL_DATA_API_KEY is not set.")

    headers = {"X-Auth-Token": key}
    data = _api_get(f"/competitions/{COMPETITION}/matches", headers)
    api_matches = data.get("matches", [])

    code_to_team_id = {t.code: t.id for t in Team.query.all()}

    updated_status = 0
    updated_score = 0
    updated_scorer = 0
    skipped = 0

    # We will optionally hit /matches/<id> for newly-finished matches. The free
    # tier allows 10 req/min, so we throttle.
    detail_calls = 0
    DETAIL_CAP = 8  # leave headroom under the 10-req/min ceiling

    for m_api in api_matches:
        home_code = (m_api.get("homeTeam") or {}).get("tla") or ""
        away_code = (m_api.get("awayTeam") or {}).get("tla") or ""
        home_id = code_to_team_id.get(home_code.upper())
        away_id = code_to_team_id.get(away_code.upper())
        if not home_id or not away_id:
            skipped += 1
            continue
        m_local = Match.query.filter_by(home_team_id=home_id, away_team_id=away_id).first()
        if not m_local:
            skipped += 1
            continue

        new_status = STATUS_MAP.get(m_api.get("status"), "upcoming")
        if m_local.status != new_status:
            m_local.status = new_status
            updated_status += 1

        # Only sync scores when admin hasn't already entered them
        if m_local.home_score is None:
            ft = (m_api.get("score") or {}).get("fullTime") or {}
            api_h = ft.get("home")
            api_a = ft.get("away")
            if api_h is not None and api_a is not None:
                m_local.home_score = api_h
                m_local.away_score = api_a
                updated_score += 1

        # If match is finished AND no first_scorer set yet, try the detail call
        if (m_local.status == "finished"
                and m_local.first_scorer_id is None
                and detail_calls < DETAIL_CAP):
            api_match_id = m_api.get("id")
            if api_match_id:
                time.sleep(7)  # throttle to stay under 10 req/min
                detail_calls += 1
                scorer_player_id = _fetch_first_scorer(
                    api_match_id, home_id, away_id, headers
                )
                if scorer_player_id:
                    m_local.first_scorer_id = scorer_player_id
                    updated_scorer += 1

    db.session.commit()
    return {
        "updated_status": updated_status,
        "updated_score": updated_score,
        "updated_scorer": updated_scorer,
        "skipped": skipped,
    }
