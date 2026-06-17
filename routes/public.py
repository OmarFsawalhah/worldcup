from flask import Blueprint, render_template, request, redirect, url_for, abort, flash, jsonify
from flask_login import login_required, current_user

from models import db, Match, Team, Player, Prediction, Notification
from scoring import user_total_points, user_exact_score_hits, prediction_breakdown
from i18n import t

bp = Blueprint("public", __name__)

STAGE_ORDER = ["group", "r32", "r16", "qf", "sf", "third", "final"]


@bp.route("/")
def dashboard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    # Lazy fire of "match starting in ~1h" reminders — runs once per dashboard
    # load, fully idempotent so it's safe to call constantly.
    try:
        from services.notifications import fire_starting_match_reminders
        fire_starting_match_reminders()
    except Exception:
        import logging
        logging.exception("starting reminders failed")

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


@bp.route("/match/<int:match_id>", methods=["GET", "POST"])
@login_required
def match_detail(match_id):
    match = db.session.get(Match, match_id) or abort(404)
    players = Player.query.filter(
        Player.team_id.in_([match.home_team_id, match.away_team_id])
    ).order_by(Player.team_id, Player.shirt_number).all()

    prediction = Prediction.query.filter_by(user_id=current_user.id, match_id=match.id).first()

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

            db.session.commit()
            flash(t("match.thanks") if action == "wizard" else t("match.updated"), "success")
            return redirect(url_for("public.match_detail", match_id=match.id, done=1))

    home_players = [p for p in players if p.team_id == match.home_team_id]
    away_players = [p for p in players if p.team_id == match.away_team_id]
    return render_template(
        "match.html", match=match,
        home_players=home_players, away_players=away_players,
        prediction=prediction,
    )


@bp.route("/leaderboard")
def leaderboard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    from models import User
    # Hide superusers from the public leaderboard.
    users = User.query.filter(
        (User.is_superuser.is_(False)) | (User.is_superuser.is_(None))
    ).all()
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

    pred_rows = []
    for p in sorted(preds, key=lambda x: x.match.kickoff_utc):
        pred_rows.append({"p": p, "match": p.match, "bd": prediction_breakdown(p, p.match)})

    pred_total = sum(r["bd"]["total"] for r in pred_rows)
    total = pred_total

    return render_template(
        "profile.html",
        pred_rows=pred_rows, triv_rows=[],
        pred_total=pred_total, triv_total=0, total=total,
    )


# ============================================================
#  In-app notifications
# ============================================================

@bp.route("/notifications")
@login_required
def notifications():
    from services.notifications import list_for_user
    items = list_for_user(current_user.id, limit=100)
    return render_template("notifications.html", items=items)


@bp.route("/notifications/unread_count")
@login_required
def notifications_unread_count():
    from services.notifications import unread_count_for
    return jsonify({"unread": unread_count_for(current_user.id)})


@bp.route("/notifications/<int:nid>/read", methods=["POST"])
@login_required
def notification_read(nid):
    n = db.session.get(Notification, nid) or abort(404)
    if n.user_id != current_user.id:
        abort(403)
    n.is_read = True
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/notifications/mark_all_read", methods=["POST"])
@login_required
def notifications_mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update(
        {"is_read": True}
    )
    db.session.commit()
    return redirect(url_for("public.notifications"))
