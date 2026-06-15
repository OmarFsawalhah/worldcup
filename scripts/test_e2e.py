"""End-to-end smoke test using the Flask test client.

Runs in-process against a temporary SQLite DB so it never touches your
real worldcup.db. Reports PASS/FAIL for every key user flow.

Usage:
    python scripts/test_e2e.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# Use a throwaway SQLite DB so we don't touch the real one
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{TMP_DB}"
os.environ["SECRET_KEY"] = "test-secret"

from app import app, db  # noqa: E402
from models import User, Team, Player, Match, Prediction, TriviaQuestion, TriviaAnswer, QuestionBank, MatchTrivia  # noqa: E402

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append((name, detail))
        print(f"  FAIL  {name}  — {detail}")


def seed_minimal():
    """Build a tiny in-memory tournament: 2 teams, 5 players each, 1 future match,
    1 already-locked match, 4 admins, 1 trivia question."""
    with app.app_context():
        db.drop_all()
        db.create_all()
        # auto-migrate adds new columns to a brand-new DB; harmless to skip
        from app import _auto_migrate
        _auto_migrate()

        ksa = Team(code="KSA", name_en="Saudi Arabia", name_ar="السعودية",
                   flag_emoji="🇸🇦", group_letter="F")
        mar = Team(code="MAR", name_en="Morocco", name_ar="المغرب",
                   flag_emoji="🇲🇦", group_letter="F")
        db.session.add_all([ksa, mar])
        db.session.flush()

        for i in range(1, 6):
            db.session.add(Player(team_id=ksa.id, name_en=f"KSA Player {i}",
                                  name_ar=f"لاعب سعودي {i}", position="MID", shirt_number=i))
            db.session.add(Player(team_id=mar.id, name_en=f"MAR Player {i}",
                                  name_ar=f"لاعب مغربي {i}", position="MID", shirt_number=i))

        now = datetime.now(timezone.utc)
        future_match = Match(stage="group", group_letter="F",
                             home_team_id=ksa.id, away_team_id=mar.id,
                             kickoff_utc=now + timedelta(hours=2), status="upcoming")
        locked_match = Match(stage="group", group_letter="F",
                             home_team_id=mar.id, away_team_id=ksa.id,
                             kickoff_utc=now - timedelta(hours=1), status="upcoming")
        db.session.add_all([future_match, locked_match])

        # 4 admins, all with must_change_password=True
        from scripts.seed import ADMIN_USERNAMES, DEFAULT_ADMIN_PASSWORD
        for u in ADMIN_USERNAMES:
            user = User(username=u, is_admin=True, must_change_password=True)
            user.set_password(DEFAULT_ADMIN_PASSWORD)
            db.session.add(user)
        db.session.commit()
        return future_match.id, locked_match.id


def main():
    print("=" * 60)
    print("World Cup 2026 Predictor — End-to-End Smoke Test")
    print("=" * 60)
    future_id, locked_id = seed_minimal()

    print("\n[1] Anonymous access")
    c = app.test_client()
    r = c.get("/")
    check("anon root redirects to login", r.status_code == 302 and "/login" in r.location, f"got {r.status_code} {r.location}")
    r = c.get("/leaderboard")
    check("anon leaderboard redirects", r.status_code == 302, f"got {r.status_code}")
    r = c.get("/login")
    check("login page is public", r.status_code == 200)
    # nav should hide protected links when logged out
    check("logged-out nav hides dashboard link", b"nav.dashboard" not in r.data and b"Matches" not in r.data)

    print("\n[2] User registration & login")
    c = app.test_client()
    r = c.post("/register", data={"username": "alice", "password": "secret123", "password_confirm": "secret123"},
               follow_redirects=False)
    check("register succeeds", r.status_code == 302)
    r = c.get("/")
    check("registered user reaches dashboard", r.status_code == 200)
    check("dashboard shows match teams", b"Saudi Arabia" in r.data or b"Morocco" in r.data)

    print("\n[3] Prediction on future match")
    r = c.get(f"/match/{future_id}")
    check("match page loads", r.status_code == 200)
    check("prediction form rendered (not locked)", b'name="home_score"' in r.data)
    r = c.post(f"/match/{future_id}", data={
        "action": "predict", "winner_prediction": "home",
        "home_score": "2", "away_score": "1",
        "first_scorer_id": "", "motm_id": "",
    }, follow_redirects=False)
    check("prediction POST returns redirect", r.status_code == 302)
    with app.app_context():
        alice = User.query.filter_by(username="alice").first()
        p = Prediction.query.filter_by(user_id=alice.id, match_id=future_id).first()
    check("prediction saved in DB", p is not None and p.winner_prediction == "home" and p.home_score == 2 and p.away_score == 1, f"p={p}")

    print("\n[4] Locked match blocks prediction")
    r = c.get(f"/match/{locked_id}")
    check("locked match page loads", r.status_code == 200)
    check("locked match shows 'locked' message", b"locked" in r.data.lower() or "مغلقة".encode() in r.data)
    check("locked match has NO score input form", b'name="home_score"' not in r.data)
    r = c.post(f"/match/{locked_id}", data={
        "action": "predict", "winner_prediction": "draw", "home_score": "5", "away_score": "5",
    }, follow_redirects=False)
    with app.app_context():
        p = Prediction.query.filter_by(user_id=alice.id, match_id=locked_id).first()
    check("locked match POST does NOT save prediction", p is None)

    print("\n[5] Admin first-login forces password change")
    c2 = app.test_client()
    r = c2.post("/login", data={"username": "anas", "password": "admin123"}, follow_redirects=False)
    check("admin login succeeds", r.status_code == 302)
    r = c2.get("/", follow_redirects=False)
    check("admin redirected to change-password page", r.status_code == 302 and "change-password" in r.location, f"got {r.location}")
    r = c2.get("/admin/matches", follow_redirects=False)
    check("admin admin-area also blocked until pw change", "change-password" in r.location)
    r = c2.post("/change-password", data={
        "current_password": "admin123",
        "new_password": "newAdminPass!",
        "new_password_confirm": "newAdminPass!",
    }, follow_redirects=False)
    check("password change POST succeeds", r.status_code == 302)
    with app.app_context():
        anas = User.query.filter_by(username="anas").first()
    check("must_change_password cleared", anas.must_change_password is False)
    check("new password works (old fails)", anas.check_password("newAdminPass!") and not anas.check_password("admin123"))
    r = c2.get("/", follow_redirects=False)
    check("admin reaches dashboard after pw change", r.status_code == 200)

    print("\n[6] Seed the question bank with one canned question")
    with app.app_context():
        QuestionBank.query.delete()
        MatchTrivia.query.delete()
        db.session.add(QuestionBank(
            question_ar="سؤال البنك التجريبي؟",
            choices_json=json.dumps(["خيار أ", "خيار ب", "خيار ج"], ensure_ascii=False),
            correct_index=1,
            difficulty="medium",
        ))
        db.session.commit()
        bank_before = QuestionBank.query.count()
    check("question bank seeded with 1 question", bank_before == 1)

    print("\n[7] Alice opens match -> gets a random question + answers via wizard")
    # Push match kickoff to within 1h so things stay unlocked
    with app.app_context():
        m = db.session.get(Match, future_id)
        m.kickoff_utc = datetime.now(timezone.utc) + timedelta(minutes=30)
        db.session.commit()
    r = c.get(f"/match/{future_id}")
    check("alice sees trivia step in wizard", b'name="trivia_choice_index"' in r.data)
    with app.app_context():
        mt = MatchTrivia.query.filter_by(user_id=alice.id, match_id=future_id).first()
        bank_after = QuestionBank.query.count()
    check("MatchTrivia row created for alice", mt is not None)
    check("question removed from bank (197 -> N-1)", bank_after == bank_before - 1, f"got {bank_after}")
    # Alice submits the wizard with the correct trivia answer (index 1).
    r = c.post(f"/match/{future_id}", data={
        "action": "wizard",
        "winner_prediction": "home",
        "home_score": "2", "away_score": "1",
        "trivia_choice_index": "1",
    }, follow_redirects=False)
    check("wizard submit succeeds", r.status_code == 302)
    with app.app_context():
        mt = MatchTrivia.query.filter_by(user_id=alice.id, match_id=future_id).first()
    check("alice trivia answer saved (instant)", mt.choice_index == 1)
    check("alice trivia awarded +3 instantly", mt.points_awarded == 3, f"got {mt.points_awarded}")

    print("\n[8] Save result, leaderboard does NOT move until Calc Points (for prediction pts)")
    # Lock the match by moving kickoff to the past
    with app.app_context():
        m = db.session.get(Match, future_id)
        m.kickoff_utc = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.session.commit()
    r = c2.post(f"/admin/matches/{future_id}/result", data={
        "home_score": "2", "away_score": "1",
        "first_scorer_id": "", "motm_id": "",
    }, follow_redirects=False)
    check("save result POST succeeds", r.status_code == 302)
    with app.app_context():
        p = Prediction.query.filter_by(user_id=alice.id, match_id=future_id).first()
    check("alice's prediction points still 0 (pending Calc)", p.points_awarded == 0)

    print("\n[9] Calc Points awards prediction points (trivia already scored)")
    r = c2.post(f"/admin/matches/{future_id}/calc_points", follow_redirects=False)
    check("calc points POST succeeds", r.status_code == 302)
    with app.app_context():
        p = Prediction.query.filter_by(user_id=alice.id, match_id=future_id).first()
        mt = MatchTrivia.query.filter_by(user_id=alice.id, match_id=future_id).first()
    # Alice predicted home win + 2-1 → +3 winner + +2 exact bonus = 5
    check("alice prediction awarded 5 pts (winner+exact bonus)", p.points_awarded == 5, f"got {p.points_awarded}")
    check("alice trivia still +3 (scored at submit time)", mt.points_awarded == 3, f"got {mt.points_awarded}")

    print("\n[10] Leaderboard reflects scoring; profile shows breakdown")
    r = c.get("/leaderboard")
    check("leaderboard returns 200", r.status_code == 200)
    check("alice on leaderboard with 8 points", b"alice" in r.data and b"8" in r.data)
    r = c.get("/profile")
    check("profile returns 200", r.status_code == 200)
    check("profile shows 'From predictions' breakdown", b"From predictions" in r.data or "من التوقعات".encode() in r.data)
    check("profile shows 'From trivia' breakdown", b"From trivia" in r.data or "من الأسئلة".encode() in r.data)
    check("profile shows scoring legend", b"Scoring legend" in r.data or "كيف تُحسب".encode() in r.data)

    print("\n[11] i18n: switch to Arabic")
    r = c.get("/lang/ar", follow_redirects=False)
    check("lang switch redirects", r.status_code == 302)
    r = c.get("/")
    check("dashboard renders RTL", b'dir="rtl"' in r.data)
    check("dashboard shows Arabic title", "توقعات".encode() in r.data)

    print("\n[12] Admin Users page lists everyone")
    r = c2.get("/admin/users")
    check("admin users page returns 200", r.status_code == 200)
    check("admin users page lists alice", b"alice" in r.data)
    check("admin users page lists anas as Admin", b"anas" in r.data)

    print("\n[12.5] Manual point adjustment by admin")
    with app.app_context():
        alice_id = User.query.filter_by(username="alice").first().id
    r = c2.post(f"/admin/users/{alice_id}/adjust", data={"bonus_points": "10"},
                follow_redirects=False)
    check("bonus POST succeeds", r.status_code == 302)
    with app.app_context():
        from scoring import user_total_points
        new_total = user_total_points(alice_id)
    check("user_total_points includes bonus (was 8, now 18)", new_total == 18, f"got {new_total}")

    print("\n[13] Nav active highlight")
    r = c.get("/profile")
    check("active nav uses yellow highlight class", b"bg-yellow-400" in r.data)

    print("\n[14] Flag rendering")
    r = c.get("/")
    check("dashboard uses flagcdn image flags", b"flagcdn.com" in r.data)

    print("\n[15] Logout clears session")
    r = c.get("/logout", follow_redirects=False)
    check("logout redirects to login", r.status_code == 302 and "/login" in r.location)
    r = c.get("/")
    check("after logout root redirects to login again", r.status_code == 302)

    print("\n" + "=" * 60)
    print(f"RESULTS:  {len(PASSED)} passed,  {len(FAILED)} failed")
    print("=" * 60)
    if FAILED:
        print("\nFailures:")
        for name, detail in FAILED:
            print(f"  - {name}: {detail}")
        sys.exit(1)
    print("\nAll critical flows working.")
    os.unlink(TMP_DB)


if __name__ == "__main__":
    main()
