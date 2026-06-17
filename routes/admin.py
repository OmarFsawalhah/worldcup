import json
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, abort, flash
from flask_login import login_required, current_user

from models import db, Match, Team, Player, Prediction, User
from scoring import score_match, user_total_points, user_exact_score_hits
from i18n import t

bp = Blueprint("admin", __name__, url_prefix="/admin")

STAGES = ["group", "r32", "r16", "qf", "sf", "third", "final"]


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        if not current_user.is_admin:
            abort(403)
        return fn(*a, **kw)
    return wrapper


def superuser_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        if not getattr(current_user, "is_superuser", False):
            abort(403)
        return fn(*a, **kw)
    return wrapper


@bp.route("/")
@admin_required
def home():
    return redirect(url_for("admin.matches"))


@bp.route("/matches")
@admin_required
def matches():
    all_matches = Match.query.order_by(Match.kickoff_utc.asc()).all()
    return render_template("admin/matches.html", matches=all_matches)


@bp.route("/matches/new", methods=["GET", "POST"])
@admin_required
def match_new():
    if request.method == "POST":
        m = _populate_match(Match(), request.form)
        db.session.add(m)
        db.session.commit()
        flash(t("admin.saved"), "success")
        return redirect(url_for("admin.matches"))
    teams = Team.query.order_by(Team.name_en).all()
    return render_template("admin/match_form.html", match=None, teams=teams, stages=STAGES)


@bp.route("/matches/<int:mid>/edit", methods=["GET", "POST"])
@admin_required
def match_edit(mid):
    m = db.session.get(Match, mid) or abort(404)
    if request.method == "POST":
        _populate_match(m, request.form)
        db.session.commit()
        flash(t("admin.saved"), "success")
        return redirect(url_for("admin.matches"))
    teams = Team.query.order_by(Team.name_en).all()
    return render_template("admin/match_form.html", match=m, teams=teams, stages=STAGES)


@bp.route("/matches/<int:mid>/delete", methods=["POST"])
@admin_required
def match_delete(mid):
    m = db.session.get(Match, mid) or abort(404)
    db.session.delete(m)
    db.session.commit()
    flash(t("admin.deleted"), "success")
    return redirect(url_for("admin.matches"))


@bp.route("/matches/<int:mid>/result", methods=["GET", "POST"])
@admin_required
def match_result(mid):
    m = db.session.get(Match, mid) or abort(404)
    players = Player.query.filter(
        Player.team_id.in_([m.home_team_id, m.away_team_id])
    ).order_by(Player.team_id, Player.shirt_number).all()
    if request.method == "POST":
        try:
            m.home_score = int(request.form.get("home_score"))
            m.away_score = int(request.form.get("away_score"))
        except (TypeError, ValueError):
            flash("Invalid score", "error")
            return redirect(url_for("admin.match_result", mid=mid))
        fs = request.form.get("first_scorer_id") or None
        mm = request.form.get("motm_id") or None
        m.first_scorer_id = int(fs) if fs else None
        m.motm_id = int(mm) if mm else None
        m.status = "finished"
        db.session.commit()
        flash(t("admin.result_saved_pending"), "success")
        return redirect(url_for("admin.matches"))
    return render_template("admin/result.html", match=m, players=players)


@bp.route("/matches/<int:mid>/calc_points", methods=["POST"])
@admin_required
def match_calc_points(mid):
    m = db.session.get(Match, mid) or abort(404)
    if m.home_score is None or m.away_score is None:
        flash("Save the result first.", "error")
        return redirect(url_for("admin.matches"))
    # Superusers can always recalc, even if another admin claimed it.
    if (m.calculated_by_id
            and m.calculated_by_id != current_user.id
            and not getattr(current_user, "is_superuser", False)):
        flash(t("admin.already_calculated_by", who=m.calculated_by.username), "error")
        return redirect(url_for("admin.matches"))
    score_match(m)
    m.calculated_by_id = current_user.id
    db.session.commit()
    flash(t("admin.points_calculated"), "success")
    return redirect(url_for("admin.matches"))


@bp.route("/refresh-api", methods=["POST"])
@admin_required
def refresh_api():
    from services.api_refresh import refresh_match_statuses
    try:
        result = refresh_match_statuses()
    except Exception as e:
        flash(f"Refresh failed: {e}", "error")
        return redirect(url_for("admin.matches"))
    flash(t("admin.refresh_done",
            statuses=result["updated_status"],
            scores=result["updated_score"],
            scorers=result.get("updated_scorer", 0)),
          "success")
    return redirect(url_for("admin.matches"))


@bp.route("/users")
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.asc()).all()
    rows = []
    for u in all_users:
        rows.append({
            "user": u,
            "points": user_total_points(u.id),
            "exact": user_exact_score_hits(u.id),
            "predictions": u.predictions.count(),
            "bonus": u.bonus_points,
        })
    rows.sort(key=lambda r: (r["user"].is_admin, -r["points"], r["user"].created_at))
    return render_template("admin/users.html", rows=rows)


@bp.route("/users/<int:uid>/adjust", methods=["POST"])
@admin_required
def user_adjust(uid):
    u = db.session.get(User, uid) or abort(404)
    try:
        bonus = int(request.form.get("bonus_points") or 0)
    except ValueError:
        flash("Invalid number.", "error")
        return redirect(url_for("admin.users"))
    delta = bonus - (u.bonus_points or 0)
    u.bonus_points = bonus
    db.session.commit()
    if delta != 0:
        try:
            from services.notifications import notify_manual_bonus
            notify_manual_bonus(u, delta, current_user.username)
        except Exception:
            import logging
            logging.exception("notify_manual_bonus failed")
    flash(t("admin.bonus_saved"), "success")
    return redirect(url_for("admin.users"))


@bp.route("/matches/<int:mid>/predictions")
@admin_required
def match_predictions(mid):
    m = db.session.get(Match, mid) or abort(404)
    preds = Prediction.query.filter_by(match_id=mid).all()
    preds.sort(key=lambda p: (-p.points_awarded, p.user.username))
    return render_template("admin/predictions.html", match=m, predictions=preds)


def _populate_match(m, form):
    m.stage = form.get("stage")
    gl = form.get("group_letter") or None
    m.group_letter = gl if m.stage == "group" else None
    m.home_team_id = int(form.get("home_team_id"))
    m.away_team_id = int(form.get("away_team_id"))
    ko = form.get("kickoff_utc")
    # accept "2026-06-13T18:00" or with seconds
    m.kickoff_utc = datetime.fromisoformat(ko)
    m.venue = form.get("venue") or None
    return m


# ============================================================
#                    Superuser-only views
# ============================================================

@bp.route("/users/<int:uid>")
@superuser_required
def user_details(uid):
    """Full points breakdown for one user (every prediction + bonus + grand total)."""
    from scoring import prediction_breakdown
    user = db.session.get(User, uid) or abort(404)

    preds = Prediction.query.filter_by(user_id=uid).all()
    pred_rows = []
    for p in sorted(preds, key=lambda x: x.match.kickoff_utc):
        pred_rows.append({
            "p": p,
            "match": p.match,
            "bd": prediction_breakdown(p, p.match),
        })

    pred_total = sum(r["bd"]["total"] for r in pred_rows)
    total = pred_total + (user.bonus_points or 0)

    return render_template(
        "admin/user_details.html",
        user=user,
        pred_rows=pred_rows,
        triv_rows=[],
        pred_total=pred_total,
        triv_total=0,
        total=total,
    )


@bp.route("/points-log")
@superuser_required
def points_log():
    """Timeline of points: for each finished match (chronological), for each
    user, show points earned and running total. Lets you see 'before vs after'
    for any match."""
    # Find all finished matches in kickoff order
    finished = (
        Match.query
        .filter(Match.status == "finished")
        .order_by(Match.kickoff_utc.asc())
        .all()
    )
    # All non-zero participants — pick everyone with any prediction or trivia
    users = User.query.order_by(User.username).all()

    # Build per-user delta + running total for each match
    # Result: list of {match, kickoff, rows: [{username, pred_pts, triv_pts, delta, running}]}
    running = {u.id: u.bonus_points or 0 for u in users}  # start running with bonus
    timeline = []
    # First row: "Starting state" (just bonuses, if any)
    if any(running.values()):
        timeline.append({
            "label": "Starting bonuses",
            "kickoff": None,
            "rows": [
                {"user_id": u.id, "username": u.username, "pred_pts": 0,
                 "triv_pts": 0, "delta": running[u.id], "running": running[u.id]}
                for u in users if running[u.id] != 0
            ],
        })
    for m in finished:
        match_rows = []
        for u in users:
            pred = Prediction.query.filter_by(user_id=u.id, match_id=m.id).first()
            pred_pts = pred.points_awarded if pred else 0
            delta = pred_pts
            if delta == 0 and not pred:
                continue  # user wasn't involved in this match at all
            running[u.id] += delta
            match_rows.append({
                "user_id": u.id, "username": u.username,
                "pred_pts": pred_pts, "triv_pts": 0,
                "delta": delta, "running": running[u.id],
            })
        if match_rows:
            timeline.append({
                "match": m,
                "kickoff": m.kickoff_utc,
                "rows": match_rows,
            })

    return render_template("admin/points_log.html", timeline=timeline, users=users)
