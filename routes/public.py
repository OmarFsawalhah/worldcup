import json
import random

from flask import Blueprint, render_template, request, redirect, url_for, abort, flash
from flask_login import login_required, current_user
from sqlalchemy import func

from models import db, Match, Team, Player, Prediction, QuestionBank, MatchTrivia
from scoring import user_total_points, user_exact_score_hits, prediction_breakdown, POINTS_TRIVIA
from i18n import t

bp = Blueprint("public", __name__)

STAGE_ORDER = ["group", "r32", "r16", "qf", "sf", "third", "final"]


@bp.route("/")
def dashboard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    matches = Match.query.order_by(Match.kickoff_utc.asc()).all()
    predicted_ids = {p.match_id for p in
                     Prediction.query.with_entities(Prediction.match_id)
                     .filter_by(user_id=current_user.id).all()}
    grouped = {}
    for m in matches:
        key = ("group", m.group_letter or "?") if m.stage == "group" else (m.stage, None)
        grouped.setdefault(key, []).append(m)

    def sort_key(k):
        stage, letter = k
        if stage == "group":
            return (0, letter or "")
        return (1 + STAGE_ORDER.index(stage), "")

    sections = sorted(grouped.items(), key=lambda kv: sort_key(kv[0]))
    return render_template("dashboard.html", sections=sections, predicted_ids=predicted_ids)


def _assign_random_question(user_id, match_id):
    """Pop one random question from the bank and snapshot it into MatchTrivia
    for this user+match. Returns the new MatchTrivia row, or None if the bank
    is empty. Caller commits."""
    # Random pick — use SQLAlchemy's func.random() (SQLite) / random() (Postgres).
    # Both engines support func.random() via the orderby trick.
    bank_row = QuestionBank.query.order_by(func.random()).first()
    if not bank_row:
        return None
    mt = MatchTrivia(
        user_id=user_id,
        match_id=match_id,
        question_ar=bank_row.question_ar,
        choices_json=bank_row.choices_json,
        correct_index=bank_row.correct_index,
        choice_index=None,
        points_awarded=0,
    )
    db.session.add(mt)
    db.session.delete(bank_row)
    db.session.flush()  # surface IntegrityError before caller commits
    return mt


@bp.route("/match/<int:match_id>", methods=["GET", "POST"])
@login_required
def match_detail(match_id):
    match = db.session.get(Match, match_id) or abort(404)
    players = Player.query.filter(
        Player.team_id.in_([match.home_team_id, match.away_team_id])
    ).order_by(Player.team_id, Player.shirt_number).all()

    prediction = Prediction.query.filter_by(user_id=current_user.id, match_id=match.id).first()

    # Look up the user's MatchTrivia for this match. If the match is still
    # predictable AND none exists yet, lazily draw one from the bank.
    user_trivia = MatchTrivia.query.filter_by(
        user_id=current_user.id, match_id=match.id
    ).first()
    if user_trivia is None and not match.is_locked() and request.method == "GET":
        try:
            user_trivia = _assign_random_question(current_user.id, match.id)
            if user_trivia is not None:
                db.session.commit()
        except Exception:
            db.session.rollback()
            user_trivia = None

    if request.method == "POST":
        action = request.form.get("action")
        if action in ("predict", "wizard"):
            if match.is_locked():
                flash(t("match.locked_msg"), "error")
                return redirect(url_for("public.match_detail", match_id=match.id))
            winner = request.form.get("winner_prediction") or None
            if winner not in (None, "home", "draw", "away"):
                winner = None
            hs_raw = (request.form.get("home_score") or "").strip()
            as_raw = (request.form.get("away_score") or "").strip()
            hs = int(hs_raw) if hs_raw else None
            as_ = int(as_raw) if as_raw else None
            if (hs is None) != (as_ is None):
                hs = as_ = None
            fs = request.form.get("first_scorer_id") or None
            mm = request.form.get("motm_id") or None
            fs = int(fs) if fs else None
            mm = int(mm) if mm else None
            if prediction is None:
                prediction = Prediction(user_id=current_user.id, match_id=match.id,
                                        winner_prediction=winner,
                                        home_score=hs, away_score=as_,
                                        first_scorer_id=fs, motm_id=mm)
                db.session.add(prediction)
            else:
                prediction.winner_prediction = winner
                prediction.home_score = hs
                prediction.away_score = as_
                prediction.first_scorer_id = fs
                prediction.motm_id = mm

            # Wizard may also include the trivia answer (against user_trivia).
            if action == "wizard" and user_trivia is not None and user_trivia.choice_index is None:
                triv_raw = (request.form.get("trivia_choice_index") or "").strip()
                if triv_raw != "":
                    try:
                        choice = int(triv_raw)
                        choices = json.loads(user_trivia.choices_json)
                        if 0 <= choice < len(choices):
                            user_trivia.choice_index = choice
                            user_trivia.points_awarded = (
                                POINTS_TRIVIA if choice == user_trivia.correct_index else 0
                            )
                    except (TypeError, ValueError):
                        pass

            db.session.commit()
            flash(t("match.thanks") if action == "wizard" else t("match.updated"), "success")
            return redirect(url_for("public.match_detail", match_id=match.id, done=1))

    home_players = [p for p in players if p.team_id == match.home_team_id]
    away_players = [p for p in players if p.team_id == match.away_team_id]
    trivia_choices = json.loads(user_trivia.choices_json) if user_trivia else []
    return render_template(
        "match.html", match=match,
        home_players=home_players, away_players=away_players,
        prediction=prediction,
        user_trivia=user_trivia,
        trivia_choices=trivia_choices,
    )


@bp.route("/leaderboard")
def leaderboard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    from models import User
    users = User.query.all()
    rows = []
    for u in users:
        rows.append({
            "username": u.username,
            "is_admin": u.is_admin,
            "points": user_total_points(u.id),
            "exact": user_exact_score_hits(u.id),
            "created_at": u.created_at,
        })
    rows.sort(key=lambda r: (-r["points"], -r["exact"], r["created_at"]))
    return render_template("leaderboard.html", rows=rows)


@bp.route("/profile")
@login_required
def profile():
    preds = Prediction.query.filter_by(user_id=current_user.id).all()
    # Trivia rows come from MatchTrivia now (only show ones the user actually answered).
    trivia_rows_raw = (
        MatchTrivia.query
        .filter_by(user_id=current_user.id)
        .filter(MatchTrivia.choice_index.isnot(None))
        .all()
    )

    pred_rows = []
    for p in sorted(preds, key=lambda x: x.match.kickoff_utc):
        pred_rows.append({"p": p, "match": p.match, "bd": prediction_breakdown(p, p.match)})

    triv_rows = []
    for a in trivia_rows_raw:
        m = a.match
        choices = json.loads(a.choices_json)
        triv_rows.append({
            "answer": a,
            "match": m,
            "question_ar": a.question_ar,
            "your_choice": choices[a.choice_index] if a.choice_index is not None and 0 <= a.choice_index < len(choices) else "?",
            "correct_choice": choices[a.correct_index] if 0 <= a.correct_index < len(choices) else "?",
            "is_correct": a.choice_index == a.correct_index,
            "pts": a.points_awarded,
        })
    triv_rows.sort(key=lambda r: r["match"].kickoff_utc)

    pred_total = sum(r["bd"]["total"] for r in pred_rows)
    triv_total = sum(r["pts"] for r in triv_rows)
    total = pred_total + triv_total

    return render_template(
        "profile.html",
        pred_rows=pred_rows, triv_rows=triv_rows,
        pred_total=pred_total, triv_total=triv_total, total=total,
    )
