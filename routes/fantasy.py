"""Fantasy game routes — squad picker, lineup, view."""
from collections import Counter
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from models import db, Player, Team, FantasySquad, FantasyPick, Match
from i18n import t
from fantasy_scoring import points_map_for_players, user_fantasy_breakdown, user_fantasy_total

bp = Blueprint("fantasy", __name__, url_prefix="/fantasy")

# Stage groups for the transfer-window machinery.
# "third" + "final" share a phase (they're played in the same window).
PHASE_STAGES = [
    ("group", ["group"]),
    ("r32",   ["r32"]),
    ("r16",   ["r16"]),
    ("qf",    ["qf"]),
    ("sf",    ["sf"]),
    ("final", ["third", "final"]),
]


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def transfer_window_state() -> dict:
    """Return a dict describing the current transfer window:

    {
      'status': 'open' | 'locked',
      'phase_in_play': <phase_key> or None,
      'next_event_at': datetime UTC (when the current state flips), or None,
      'next_event_type': 'closes' | 'opens' | None,
      'next_phase': <phase_key> or None,   # phase that closes the window
    }

    Rules:
    - Before any match has kicked off → status='open', next_event_type='closes'
      at the FIRST upcoming match's kickoff. next_phase=first stage.
    - A phase is "in play" if its first match has kicked off and not all of
      its matches have finished. While a phase is in play → status='locked',
      next_event_type='opens' at the LAST match's kickoff+~3h (= when result
      is expected). For simplicity we use the latest kickoff_utc in the phase.
    - Between phases (no in-play phase, and a future phase exists) →
      status='open', next_event_type='closes' at the next phase's first kickoff.
    - After the final match → status='locked' permanently (no more transfers,
      and no more matches).
    """
    now = _utcnow()
    state = {
        "status": "open",
        "phase_in_play": None,
        "next_event_at": None,
        "next_event_type": None,
        "next_phase": None,
    }

    all_matches = Match.query.order_by(Match.kickoff_utc.asc()).all()
    if not all_matches:
        return state  # no fixtures yet → window stays open

    # Group matches by phase
    phase_matches = {key: [] for key, _ in PHASE_STAGES}
    for m in all_matches:
        for key, stages in PHASE_STAGES:
            if m.stage in stages:
                phase_matches[key].append(m)
                break

    # Find phase currently in play
    in_play = None
    for key, _ in PHASE_STAGES:
        ms = phase_matches.get(key, [])
        if not ms:
            continue
        first_ko = min(m.kickoff_utc for m in ms)
        # "phase complete" = every match has has_finished() True
        all_done = all(m.has_finished() for m in ms)
        if first_ko <= now and not all_done:
            in_play = key
            break

    if in_play:
        state["status"] = "locked"
        state["phase_in_play"] = in_play
        ms = phase_matches[in_play]
        # Window reopens after the LAST match of this phase finishes.
        # We approximate "finishes" as kickoff + 2 hours (most matches end by then).
        from datetime import timedelta
        last_ko = max(m.kickoff_utc for m in ms)
        state["next_event_at"] = last_ko + timedelta(hours=2)
        state["next_event_type"] = "opens"
        return state

    # No phase in play → window open. When does it close?
    # = the first kickoff of the next not-yet-started phase
    for key, _ in PHASE_STAGES:
        ms = phase_matches.get(key, [])
        if not ms:
            continue
        first_ko = min(m.kickoff_utc for m in ms)
        if first_ko > now:
            state["next_event_at"] = first_ko
            state["next_event_type"] = "closes"
            state["next_phase"] = key
            return state

    # Past the last match — tournament over, lock permanently
    state["status"] = "locked"
    state["phase_in_play"] = None
    return state


def is_squad_locked() -> bool:
    """Convenience wrapper — True when transfers are not allowed."""
    return transfer_window_state()["status"] == "locked"

# Squad composition rules
SQUAD_SIZE = 15
POSITION_QUOTAS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_COUNTRY = 3
BUDGET = 100.0  # €m

# Starting XI rules
STARTERS = 11
MIN_FORMATION = {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}
MAX_FORMATION = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}


def _get_squad(create_if_missing: bool = False) -> FantasySquad | None:
    squad = FantasySquad.query.filter_by(user_id=current_user.id).first()
    if squad is None and create_if_missing:
        squad = FantasySquad(user_id=current_user.id, name=current_user.username)
        db.session.add(squad)
        db.session.flush()
    return squad


@bp.route("/")
@login_required
def home():
    squad = _get_squad()
    if squad is None or squad.picks.count() < SQUAD_SIZE:
        return redirect(url_for("fantasy.pick"))
    return redirect(url_for("fantasy.lineup"))


@bp.route("/pick", methods=["GET", "POST"])
@login_required
def pick():
    squad = _get_squad(create_if_missing=False)

    # Transfer window closed once tournament has started — BUT users who
    # have never built a squad get one free build at any time so late
    # joiners can play.
    if is_squad_locked() and squad and squad.picks.count() >= SQUAD_SIZE:
        flash(t("fantasy.locked_no_buy"), "error")
        return redirect(url_for("fantasy.lineup"))

    if request.method == "POST":
        # Player IDs come in as a single hidden field "selected_ids" (CSV)
        raw = request.form.get("selected_ids", "")
        try:
            ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
        except ValueError:
            ids = []
        ids = list(dict.fromkeys(ids))  # de-dupe, keep order

        # Validate exactly SQUAD_SIZE
        if len(ids) != SQUAD_SIZE:
            flash(t("fantasy.err_size", n=SQUAD_SIZE, got=len(ids)), "error")
            return redirect(url_for("fantasy.pick"))

        players = Player.query.filter(Player.id.in_(ids)).all()
        if len(players) != SQUAD_SIZE:
            flash(t("fantasy.err_unknown_player"), "error")
            return redirect(url_for("fantasy.pick"))

        # Position quotas
        pos_counts = Counter(p.fpl_position() for p in players)
        for pos, want in POSITION_QUOTAS.items():
            if pos_counts.get(pos, 0) != want:
                flash(t("fantasy.err_position",
                       pos=pos, want=want, got=pos_counts.get(pos, 0)), "error")
                return redirect(url_for("fantasy.pick"))

        # Country quota
        ctry_counts = Counter(p.team_id for p in players)
        bad = [tid for tid, c in ctry_counts.items() if c > MAX_PER_COUNTRY]
        if bad:
            flash(t("fantasy.err_country", max=MAX_PER_COUNTRY), "error")
            return redirect(url_for("fantasy.pick"))

        # Budget
        total = sum(float(p.price or 0) for p in players)
        if total > BUDGET + 0.001:
            flash(t("fantasy.err_budget", spent=("%.1f" % total), budget=("%.1f" % BUDGET)), "error")
            return redirect(url_for("fantasy.pick"))

        # Persist — wipe existing picks, write new ones
        if squad is None:
            squad = _get_squad(create_if_missing=True)
        else:
            FantasyPick.query.filter_by(squad_id=squad.id).delete()
            squad.captain_id = None
            squad.vice_id = None
        # Order: starters by position order (GK, DEF, MID, FWD), then bench last 4
        # By default mark all 15 as "starter=True"; the lineup page will refine
        # to exactly 11. We just store them; default starting XI = first 11 in
        # position order with a valid 1-4-4-2 formation.
        pos_order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
        players_sorted = sorted(players,
                                key=lambda p: (pos_order.get(p.fpl_position(), 9), -float(p.price or 0)))
        # Default starting XI: pick 1 GK, then 4 DEF, 4 MID, 2 FWD
        formation = {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2}  # 4-4-2
        starters_picked = {"GK": 0, "DEF": 0, "MID": 0, "FWD": 0}
        for slot_idx, p in enumerate(players_sorted, start=1):
            pos = p.fpl_position()
            want = formation.get(pos, 0)
            is_starter = starters_picked.get(pos, 0) < want
            if is_starter:
                starters_picked[pos] += 1
            db.session.add(FantasyPick(
                squad_id=squad.id, player_id=p.id,
                is_starter=is_starter, slot=slot_idx,
            ))
        db.session.commit()
        flash(t("fantasy.saved"), "success")
        return redirect(url_for("fantasy.lineup"))

    # GET — render picker
    all_players = (Player.query
                   .filter(~Player.name_en.like("%#%"))  # hide placeholders for now
                   .order_by(Player.team_id, Player.shirt_number)
                   .all())
    # Pre-compute normalized position so the template doesn't repeat the call
    all_players.sort(key=lambda p: (p.fpl_position(), p.team_id, p.shirt_number or 0))
    teams = Team.query.order_by(Team.name_en).all()
    selected_ids = [p.player_id for p in squad.picks.all()] if squad else []
    points_map = points_map_for_players([p.id for p in all_players])
    return render_template(
        "fantasy/pick.html",
        all_players=all_players, teams=teams,
        selected_ids=selected_ids,
        points_map=points_map,
        window=transfer_window_state(),
        rules=dict(squad_size=SQUAD_SIZE, quotas=POSITION_QUOTAS,
                   max_per_country=MAX_PER_COUNTRY, budget=BUDGET),
    )


@bp.route("/lineup", methods=["GET", "POST"])
@login_required
def lineup():
    squad = _get_squad()
    if squad is None or squad.picks.count() < SQUAD_SIZE:
        return redirect(url_for("fantasy.pick"))

    picks = squad.picks.all()
    by_pid = {p.player_id: p for p in picks}

    if request.method == "POST":
        starter_ids = {int(x) for x in request.form.getlist("starter") if x.isdigit()}
        captain_id = request.form.get("captain_id", type=int)
        vice_id = request.form.get("vice_id", type=int)

        # Validate the starter set
        if len(starter_ids) != STARTERS:
            flash(t("fantasy.err_starters", n=STARTERS, got=len(starter_ids)), "error")
            return redirect(url_for("fantasy.lineup"))
        if not starter_ids.issubset(set(by_pid.keys())):
            flash(t("fantasy.err_unknown_player"), "error")
            return redirect(url_for("fantasy.lineup"))

        # Formation check
        pos_count = Counter(by_pid[pid].player.fpl_position() for pid in starter_ids)
        for pos, mn in MIN_FORMATION.items():
            if pos_count.get(pos, 0) < mn:
                flash(t("fantasy.err_formation"), "error")
                return redirect(url_for("fantasy.lineup"))
        for pos, mx in MAX_FORMATION.items():
            if pos_count.get(pos, 0) > mx:
                flash(t("fantasy.err_formation"), "error")
                return redirect(url_for("fantasy.lineup"))

        # Captain + vice must both be starters and distinct
        if captain_id not in starter_ids or vice_id not in starter_ids:
            flash(t("fantasy.err_captain_must_start"), "error")
            return redirect(url_for("fantasy.lineup"))
        if captain_id == vice_id:
            flash(t("fantasy.err_captain_vice_same"), "error")
            return redirect(url_for("fantasy.lineup"))

        # Persist
        for p in picks:
            p.is_starter = (p.player_id in starter_ids)
        squad.captain_id = captain_id
        squad.vice_id = vice_id
        db.session.commit()
        flash(t("fantasy.lineup_saved"), "success")
        return redirect(url_for("fantasy.lineup"))

    # GET — render lineup editor
    points_map = points_map_for_players([pk.player_id for pk in picks])
    return render_template(
        "fantasy/lineup.html",
        squad=squad, picks=picks,
        starters=STARTERS,
        min_formation=MIN_FORMATION, max_formation=MAX_FORMATION,
        squad_locked=is_squad_locked(),
        window=transfer_window_state(),
        points_map=points_map,
    )


@bp.route("/leaderboard")
@login_required
def leaderboard():
    """Fantasy leaderboard — all users with a squad ranked by total points."""
    from models import User
    squads = FantasySquad.query.all()
    rows = []
    for sq in squads:
        if not sq.user:
            continue
        # Skip superusers / admins from the visible board, matching the
        # main leaderboard's convention.
        if getattr(sq.user, "is_superuser", False):
            continue
        total = user_fantasy_total(sq)
        rows.append({
            "user_id": sq.user.id,
            "username": sq.user.username,
            "is_admin": sq.user.is_admin,
            "total": total,
            "captain": sq.captain.name_en if sq.captain else None,
            "squad_size": sq.picks.count(),
        })
    rows.sort(key=lambda r: (-r["total"], r["username"]))
    return render_template("fantasy/leaderboard.html",
                           rows=rows,
                           window=transfer_window_state())


@bp.route("/breakdown")
@bp.route("/breakdown/<int:user_id>")
@login_required
def breakdown(user_id=None):
    """Per-user point breakdown. Defaults to current user; admins can pass
    a user_id to view anyone."""
    from models import User
    target_id = user_id or current_user.id
    if target_id != current_user.id and not current_user.is_admin:
        abort(403)
    user = db.session.get(User, target_id) or abort(404)
    squad = FantasySquad.query.filter_by(user_id=user.id).first()
    breakdown = user_fantasy_breakdown(squad) if squad else None
    return render_template("fantasy/breakdown.html",
                           user=user, squad=squad, breakdown=breakdown)
