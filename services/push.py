"""Web Push delivery — wraps pywebpush, handles VAPID keys, cleans up
expired subscriptions."""
import json
import os

from models import db, PushSubscription


_DISABLED_REASON: str | None = None


def _vapid_private_key() -> str | None:
    """Returns the PEM-formatted VAPID private key (with real newlines)."""
    raw = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if not raw:
        return None
    # python-dotenv stores multi-line values with literal "\n" — decode.
    return raw.replace("\\n", "\n")


def vapid_public_key() -> str | None:
    """Returns the urlsafe-b64 VAPID public key for the browser."""
    key = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    return key or None


def is_configured() -> bool:
    """True when both VAPID env vars are present."""
    return bool(vapid_public_key()) and bool(_vapid_private_key())


def send_push(user_id: int, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    """Send a Web Push to every active subscription for this user.
    Returns count of successful pushes. Failures are swallowed; expired
    subscriptions (404/410) are deleted.
    """
    global _DISABLED_REASON
    if not is_configured():
        _DISABLED_REASON = "VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY env vars not set"
        return 0

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        _DISABLED_REASON = "pywebpush not installed"
        return 0

    subs = PushSubscription.query.filter_by(user_id=user_id).all()
    if not subs:
        return 0

    private = _vapid_private_key()
    claim_email = os.environ.get("VAPID_CLAIM_EMAIL", "mailto:admin@example.com")
    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag or ""})

    success = 0
    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s.endpoint,
                    "keys": {"p256dh": s.p256dh, "auth": s.auth},
                },
                data=payload,
                vapid_private_key=private,
                vapid_claims={"sub": claim_email},
                timeout=10,
            )
            success += 1
        except WebPushException as e:
            # 404 = endpoint gone, 410 = subscription expired/unsubscribed
            status = getattr(e.response, "status_code", None) if e.response else None
            if status in (404, 410):
                try:
                    db.session.delete(s)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
        except Exception as e:
            import logging
            logging.warning("push send failed for sub %s: %s", s.id, e)
    return success
