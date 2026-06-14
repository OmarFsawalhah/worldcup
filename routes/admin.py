import json
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, abort, flash
from flask_login import login_required, current_user

from models import db, Match, Team, Player, TriviaQuestion, Prediction, User
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
    if m.calculated_by_id and m.calculated_by_id != current_user.id:
        flash(t("admin.already_calculated_by", who=m.calculated_by.username), "error")
        return redirect(url_for("admin.matches"))
    score_match(m)
    m.calculated_by_id = current_user.id
    db.session.commit()
    flash(t("admin.points_calculated"), "success")
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
    u.bonus_points = bonus
    db.session.commit()
    flash(t("admin.bonus_saved"), "success")
    return redirect(url_for("admin.users"))


@bp.route("/matches/<int:mid>/trivia", methods=["GET", "POST"])
@admin_required
def match_trivia(mid):
    m = db.session.get(Match, mid) or abort(404)
    q = m.trivia
    if request.method == "POST":
        question_ar = (request.form.get("question_ar") or "").strip()
        choices = [c.strip() for c in request.form.getlist("choices") if c.strip()]
        try:
            correct = int(request.form.get("correct_index"))
        except (TypeError, ValueError):
            correct = -1
        if not question_ar or len(choices) < 2 or not (0 <= correct < len(choices)):
            flash("Need a question, ≥2 choices, and a correct answer.", "error")
            return redirect(url_for("admin.match_trivia", mid=mid))
        if q is None:
            q = TriviaQuestion(match_id=m.id, question_ar=question_ar,
                               choices_json=json.dumps(choices, ensure_ascii=False),
                               correct_index=correct,
                               author_id=current_user.id)
            db.session.add(q)
        else:
            q.question_ar = question_ar
            q.choices_json = json.dumps(choices, ensure_ascii=False)
            q.correct_index = correct
            # Author stays the original creator unless the field is null (legacy rows)
            if q.author_id is None:
                q.author_id = current_user.id
        db.session.commit()
        # rescore trivia answers in case correct_index changed
        from scoring import score_trivia
        score_trivia(q)
        flash(t("admin.saved"), "success")
        return redirect(url_for("admin.matches"))
    choices = json.loads(q.choices_json) if q else ["", ""]
    return render_template("admin/trivia.html", match=m, question=q, choices=choices)


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
