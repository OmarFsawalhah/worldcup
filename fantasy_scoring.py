"""Fantasy game scoring helpers.

Reads MatchEvent rows (filled in by admin after each match) and computes
per-player fantasy points using the rules locked in docs/fantasy-build-log.md.
"""
from collections import defaultdict

from models import db, Match, MatchEvent, Player

GOAL_POINTS = {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}
CLEAN_SHEET_POINTS = {"GK": 5, "DEF": 5, "MID": 1, "FWD": 0}
CONCEDED_PENALTY = {"GK": -1, "DEF": -1, "MID": 0, "FWD": 0}  # per 2 conceded
ASSIST = 3
MOTM = 3
WIN, DRAW = 2, 1
YELLOW, RED, OWN_GOAL = -1, -3, -2
START_BONUS = 2  # appeared from kick-off
CAME_ON_BONUS = 1  # appeared as a sub only
KO_STAGES = {"r16", "qf", "sf", "third", "final"}


def player_match_points(player: Player, match: Match, event: MatchEvent) -> int:
    """Return integer fantasy points for one player in one match."""
    if not event:
        return 0
    if not (event.started or event.came_on):
        return 0

    pos = player.fpl_position()
    pts = START_BONUS if event.started else CAME_ON_BONUS

    pts += (event.goals or 0) * GOAL_POINTS.get(pos, 0)
    pts += (event.assists or 0) * ASSIST
    if event.yellow:
        pts += YELLOW
    if event.red:
        pts += RED
    pts += (event.own_goals or 0) * OWN_GOAL
    if event.is_motm:
        pts += MOTM

    # Team-level: win/draw/loss + clean sheet + conceded penalty
    if match.has_finished():
        is_home = (match.home_team_id == player.team_id)
        team_score = match.home_score if is_home else match.away_score
        opp_score = match.away_score if is_home else match.home_score
        if team_score is not None and opp_score is not None:
            if team_score > opp_score:
                pts += WIN
            elif team_score == opp_score:
                pts += DRAW

            # Clean sheet only counts for players who actually played; simplified
            # 60-min check = "started" (we don't track sub-off minutes yet).
            if event.started and opp_score == 0:
                pts += CLEAN_SHEET_POINTS.get(pos, 0)
            # Concession penalty
            if event.started and opp_score and opp_score >= 2:
                pts += CONCEDED_PENALTY.get(pos, 0) * (opp_score // 2)

    # Knockout multiplier (R16 onwards)
    if (match.stage or "").lower() in KO_STAGES:
        pts = round(pts * 1.25)
    return int(pts)


def player_total_points(player_id: int) -> int:
    """Sum of fantasy points across every match this player has appeared in."""
    rows = (db.session.query(MatchEvent, Match, Player)
            .join(Match, Match.id == MatchEvent.match_id)
            .join(Player, Player.id == MatchEvent.player_id)
            .filter(MatchEvent.player_id == player_id)
            .all())
    return sum(player_match_points(p, m, e) for (e, m, p) in rows)


def points_map_for_players(player_ids: list[int]) -> dict[int, int]:
    """Bulk version — one query, return {player_id: total_points}.
    Players with no events get 0."""
    if not player_ids:
        return {}
    rows = (db.session.query(MatchEvent, Match, Player)
            .join(Match, Match.id == MatchEvent.match_id)
            .join(Player, Player.id == MatchEvent.player_id)
            .filter(MatchEvent.player_id.in_(player_ids))
            .all())
    totals = defaultdict(int)
    for (e, m, p) in rows:
        totals[p.id] += player_match_points(p, m, e)
    # Fill zeros for players with no events
    return {pid: totals.get(pid, 0) for pid in player_ids}


# =====================================================================
#  User-level totals (used by leaderboard + breakdown pages)
# =====================================================================

def user_fantasy_breakdown(squad) -> dict:
    """Return a full breakdown for one user's FantasySquad:

    {
      'rows': [
        { 'player': Player, 'is_starter': bool, 'is_captain': bool,
          'is_vice': bool, 'raw_points': int, 'captain_bonus': int,
          'effective_points': int },
        ...
      ],
      'starters_total': int,    # sum of starters' base points
      'captain_bonus': int,     # extra +N from the captain's ×2
      'total': int,             # starters_total + captain_bonus
    }

    Notes:
    - Only starters contribute to `total`. Bench rows are shown for context
      but their `effective_points` is 0.
    - Captain bonus = raw_points (the captain doubles, so the BONUS is
      one extra copy of their raw).
    - We snapshot the *current* lineup against all historical matches.
      Proper per-phase lineup snapshots come later — for now, what you see
      live is what gets counted.
    """
    from models import FantasyPick
    picks = squad.picks.all() if squad else []
    if not picks:
        return {"rows": [], "starters_total": 0, "captain_bonus": 0, "total": 0}

    pmap = points_map_for_players([pk.player_id for pk in picks])
    captain_id = squad.captain_id
    starters_total = 0
    captain_bonus = 0
    rows = []
    for pk in picks:
        raw = pmap.get(pk.player_id, 0)
        is_captain = (captain_id == pk.player_id)
        is_vice = (squad.vice_id == pk.player_id)
        bonus = 0
        eff = 0
        if pk.is_starter:
            eff = raw
            if is_captain:
                bonus = raw
                eff += bonus
            starters_total += raw
            if is_captain:
                captain_bonus += bonus
        rows.append({
            "player": pk.player,
            "is_starter": pk.is_starter,
            "is_captain": is_captain,
            "is_vice": is_vice,
            "raw_points": raw,
            "captain_bonus": bonus,
            "effective_points": eff,
        })
    # Sort: starters first (by effective_pts desc), then bench
    rows.sort(key=lambda r: (not r["is_starter"], -r["effective_points"]))
    return {
        "rows": rows,
        "starters_total": starters_total,
        "captain_bonus": captain_bonus,
        "total": starters_total + captain_bonus,
    }


def user_fantasy_total(squad) -> int:
    """Compact version — just the total. Used by the leaderboard."""
    return user_fantasy_breakdown(squad)["total"]
