"""In-app notification triggers.

Every public function in here is best-effort: failure is logged and
swallowed so it never blocks the admin action that triggered it.

Four kinds, all delivered as Notification rows the user sees on /notifications:
- match_starting   (T-1h reminder, lazy: fired from dashboard)
- match_scored     (after Calc Points)
- round_closed     (last match of a stage finishes calc)
- manual_bonus     (admin adjusted bonus_points)
"""
from datetime import datetime, timezone, timedelta

from sqlalchemy.exc import IntegrityError

from models import db, Notification, Prediction, User, Match


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_add(notification: Notification) -> bool:
    """Add and commit a notification, returning True if it landed.
    Also fires a Web Push to all of the user's subscribed devices
    (best-effort). Swallows IntegrityError (duplicate by unique
    constraint) and any other DB error so the caller is never broken
    by notifications."""
    try:
        db.session.add(notification)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return False
    except Exception as exc:
        db.session.rollback()
        try:
            import logging
            logging.warning("Notification add failed: %s", exc)
        except Exception:
            pass
        return False

    # Fire Web Push best-effort. Never let it block the caller.
    try:
        from services.push import send_push
        send_push(
            user_id=notification.user_id,
            title="WC2026",
            body=notification.message_en,  # English by default — phone OS
                                            # owns the tray, not our i18n.
            url=notification.link_url or "/",
            tag=f"{notification.kind}-{notification.target_id or 0}",
        )
    except Exception as exc:
        try:
            import logging
            logging.warning("Web Push send failed: %s", exc)
        except Exception:
            pass
    return True


# =====================================================================
#  Triggers
# =====================================================================

def notify_match_scored(match: Match) -> int:
    """Called from scoring.score_match after every prediction is rescored.
    Creates one Notification per user who had a prediction. Returns count."""
    from flask import url_for
    try:
        link = url_for("public.match_detail", match_id=match.id)
    except RuntimeError:
        link = f"/match/{match.id}"
    home = match.home_team.name_en
    away = match.away_team.name_en
    home_ar = match.home_team.name_ar
    away_ar = match.away_team.name_ar
    n = 0
    for p in match.predictions:
        msg_en = f"{home} {match.home_score}-{match.away_score} {away} · You earned {p.points_awarded} pts"
        msg_ar = f"{home_ar} {match.home_score}-{match.away_score} {away_ar} · حصلت على {p.points_awarded} نقطة"
        ok = _safe_add(Notification(
            user_id=p.user_id, kind="match_scored", target_id=match.id,
            message_en=msg_en, message_ar=msg_ar, link_url=link,
        ))
        if ok:
            n += 1
    return n


def notify_round_closed(stage: str) -> int:
    """Called once when the last match of a stage is finalized.
    target_id = the stage encoded by its first char to fit an int — actually
    we use a hash of the stage so we get one notification per (user, stage)."""
    # Encode stage as a small int so it fits target_id (Integer column)
    stage_map = {"group": 1, "r32": 2, "r16": 3, "qf": 4, "sf": 5, "third": 6, "final": 7}
    target = stage_map.get(stage, 0)
    stage_label = {
        "group": ("Group stage", "دور المجموعات"),
        "r32":   ("Round of 32", "دور الـ32"),
        "r16":   ("Round of 16", "دور الـ16"),
        "qf":    ("Quarter-finals", "ربع النهائي"),
        "sf":    ("Semi-finals", "نصف النهائي"),
        "third": ("3rd place", "تحديد المركز الثالث"),
        "final": ("Final", "النهائي"),
    }.get(stage, (stage, stage))

    # Build leaderboard once
    from scoring import user_total_points, user_exact_score_hits
    users = User.query.filter(
        (User.is_superuser.is_(False)) | (User.is_superuser.is_(None))
    ).all()
    ranked = sorted(
        users,
        key=lambda u: (-user_total_points(u.id), -user_exact_score_hits(u.id), u.created_at),
    )
    rank = {u.id: i + 1 for i, u in enumerate(ranked)}
    n = 0
    for u in users:
        pts = user_total_points(u.id)
        msg_en = f"🏆 {stage_label[0]} done — you're #{rank[u.id]} with {pts} pts"
        msg_ar = f"🏆 انتهى {stage_label[1]} — مركزك #{rank[u.id]} بـ{pts} نقطة"
        ok = _safe_add(Notification(
            user_id=u.id, kind="round_closed", target_id=target,
            message_en=msg_en, message_ar=msg_ar, link_url="/leaderboard",
        ))
        if ok:
            n += 1
    return n


def notify_manual_bonus(user: User, delta: int, admin_username: str) -> bool:
    """Called from admin.user_adjust when bonus_points changes. delta is the
    NEW total - OLD total (may be negative). target_id stays NULL so each
    adjustment fires its own notification."""
    if delta == 0:
        return False
    sign_en = f"+{delta}" if delta > 0 else str(delta)
    msg_en = f"🎁 {admin_username} adjusted your bonus points by {sign_en}"
    msg_ar = f"🎁 {admin_username} عدّل نقاطك الإضافية بمقدار {sign_en}"
    return _safe_add(Notification(
        user_id=user.id, kind="manual_bonus", target_id=None,
        message_en=msg_en, message_ar=msg_ar, link_url="/profile",
    ))


def fire_starting_match_reminders() -> int:
    """LAZY trigger — call this from the dashboard on every load. For each
    match kicking off in the next 50–70 minutes, create a notification for
    every user who hasn't predicted it yet. Idempotent via the unique
    constraint (user_id, kind, target_id) so re-calling is cheap.
    """
    now = _utcnow()
    soon = now + timedelta(minutes=70)
    horizon_floor = now + timedelta(minutes=50)
    matches = Match.query.filter(
        Match.kickoff_utc >= horizon_floor,
        Match.kickoff_utc <= soon,
    ).all()
    if not matches:
        return 0

    users = User.query.filter(
        (User.is_superuser.is_(False)) | (User.is_superuser.is_(None))
    ).all()

    n = 0
    for m in matches:
        # Users who haven't predicted this match
        predicted_user_ids = {
            p.user_id for p in Prediction.query.filter_by(match_id=m.id).all()
        }
        home_en = m.home_team.name_en
        away_en = m.away_team.name_en
        home_ar = m.home_team.name_ar
        away_ar = m.away_team.name_ar
        link = f"/match/{m.id}"
        msg_en = f"⚽ Last hour to predict {home_en} vs {away_en}"
        msg_ar = f"⚽ آخر ساعة لتوقع {home_ar} ضد {away_ar}"
        for u in users:
            if u.id in predicted_user_ids:
                continue
            ok = _safe_add(Notification(
                user_id=u.id, kind="match_starting", target_id=m.id,
                message_en=msg_en, message_ar=msg_ar, link_url=link,
            ))
            if ok:
                n += 1
    return n


# =====================================================================
#  Read helpers used by routes / templates
# =====================================================================

def unread_count_for(user_id: int) -> int:
    return Notification.query.filter_by(user_id=user_id, is_read=False).count()


def list_for_user(user_id: int, limit: int = 50):
    return (Notification.query
            .filter_by(user_id=user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit).all())
