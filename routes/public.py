import json
from datetime import timezone

from flask import Blueprint, render_template, request, redirect, url_for, abort, flash
from flask_login import login_required, current_user

from models import db, Match, Team, Player, Prediction, TriviaQuestion, TriviaAnswer
from scoring import user_total_points, user_exact_score_hits, prediction_breakdown
from i18n import t

bp = Blueprint("public", __name__)

STAGE_ORDER = ["group", "r32", "r16", "qf", "sf", "third", "final"]


@bp.route("/")
def dashboard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    matches = Match.query.order_by(Match.kickoff_utc.asc()).all()
    # IDs of matches the current user has already predicted, for the badge
    predicted_ids = {p.match_id for p in
                     Prediction.query.with_entities(Prediction.match_id)
                     .filter_by(user_id=current_user.id).all()}
    grouped = {}
    for m in matches:
        if m.stage == "group":
            key = ("group", m.group_letter or "?")
        else:
            key = (m.stage, None)
        grouped.setdefault(key, []).append(m)

    def sort_key(k):
        stage, letter = k
        if stage == "group":
            return (0, letter or "")
        return (1 + STAGE_ORDER.index(stage), "")

    sections = sorted(grouped.items(), key=lambda kv: sort_key(kv[0]))
    return render_template("dashboard.html", sections=sections, predicted_ids=predicted_ids)


@bp.route("/match/<int:match_id>", methods=["GET", "POST"])
@login_required
def match_detail(match_id):
    match = db.session.get(Match, match_id) or abort(404)
    players = Player.query.filter(
        Player.team_id.in_([match.home_team_id, match.away_team_id])
    ).order_by(Player.team_id, Player.shirt_number).all()

    prediction = Prediction.query.filter_by(user_id=current_user.id, match_id=match.id).first()
    trivia_answer = None
    if match.trivia:
        trivia_answer = TriviaAnswer.query.filter_by(
            user_id=current_user.id, question_id=match.trivia.id
        ).first()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "predict":
            if match.is_locked():
                flash(t("match.locked_msg"), "error")
                return redirect(url_for("public.match_detail", match_id=match.id))
            winner = request.form.get("winner_prediction")
            if winner not in ("home", "draw", "away"):
                flash(t("match.winner_required"), "error")
                return redirect(url_for("public.match_detail", match_id=match.id))
            # Optional exact-score guess
            hs_raw = (request.form.get("home_score") or "").strip()
            as_raw = (request.form.get("away_score") or "").strip()
            hs = int(hs_raw) if hs_raw else None
            as_ = int(as_raw) if as_raw else None
            # Both score fields must be filled together, or both empty
            if (hs is None) != (as_ is None):
                flash(t("match.score_pair_required"), "error")
                return redirect(url_for("public.match_detail", match_id=match.id))
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
            db.session.commit()
            flash(t("match.updated"), "success")
            return redirect(url_for("public.match_detail", match_id=match.id))

        if action == "trivia" and match.trivia and match.trivia_open():
            if match.trivia.author_id == current_user.id:
                flash(t("match.trivia_author_block"), "error")
                return redirect(url_for("public.match_detail", match_id=match.id))
            try:
                choice = int(request.form.get("choice_index"))
            except (TypeError, ValueError):
                choice = -1
            choices = json.loads(match.trivia.choices_json)
            if 0 <= choice < len(choices):
                if trivia_answer is None:
                    trivia_answer = TriviaAnswer(
                        user_id=current_user.id, question_id=match.trivia.id,
                        choice_index=choice,
                    )
                    db.session.add(trivia_answer)
                else:
                    trivia_answer.choice_index = choice
                db.session.commit()
                flash(t("match.trivia_saved"), "success")
            return redirect(url_for("public.match_detail", match_id=match.id))

    home_players = [p for p in players if p.team_id == match.home_team_id]
    away_players = [p for p in players if p.team_id == match.away_team_id]
    trivia_choices = json.loads(match.trivia.choices_json) if match.trivia else []
    return render_template(
        "match.html", match=match,
        home_players=home_players, away_players=away_players,
        prediction=prediction, trivia_answer=trivia_answer,
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
    triv_answers = TriviaAnswer.query.filter_by(user_id=current_user.id).all()

    pred_rows = []
    for p in sorted(preds, key=lambda x: x.match.kickoff_utc):
        pred_rows.append({"p": p, "match": p.match, "bd": prediction_breakdown(p, p.match)})

    triv_rows = []
    for a in triv_answers:
        q = a.question
        m = q.match
        choices = json.loads(q.choices_json)
        triv_rows.append({
            "answer": a,
            "match": m,
            "question_ar": q.question_ar,
            "your_choice": choices[a.choice_index] if 0 <= a.choice_index < len(choices) else "?",
            "correct_choice": choices[q.correct_index] if 0 <= q.correct_index < len(choices) else "?",
            "is_correct": a.choice_index == q.correct_index,
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
