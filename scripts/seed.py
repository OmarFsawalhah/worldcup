"""Seed the database with teams, players, matches, and admin accounts.

Run via `seed_database.bat` or `python scripts/seed.py`."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

# allow `python scripts/seed.py` from project root
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from app import app
from models import db, User, Team, Player, Match

# Render's free Postgres sometimes takes a few seconds for the internal
# hostname (e.g. dpg-d8mvee3tqb8s73cjtnt0-a) to resolve right after a
# database restart or first deploy. Retry the initial connect for up to
# ~30s before giving up — saves the build from a one-time DNS hiccup.
def _wait_for_db(max_seconds=30, interval=2):
    import time
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    deadline = time.monotonic() + max_seconds
    attempt = 0
    while True:
        attempt += 1
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"DB ready (attempt {attempt})")
            return
        except OperationalError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            print(f"DB not ready yet ({exc.__class__.__name__}); "
                  f"retrying in {interval}s ({int(remaining)}s left)")
            time.sleep(interval)


ADMIN_USERNAMES = ["anas", "ali", "ahmad_okour"]
DEFAULT_ADMIN_PASSWORD = "admin123"

DATA_DIR = os.path.join(ROOT, "data")


def seed_teams():
    with open(os.path.join(DATA_DIR, "teams.json"), encoding="utf-8") as fh:
        rows = json.load(fh)
    for r in rows:
        if Team.query.filter_by(code=r["code"]).first():
            continue
        t = Team(code=r["code"], name_en=r["name_en"], name_ar=r["name_ar"],
                 flag_emoji=r["flag"], group_letter=r.get("group"))
        db.session.add(t)
    db.session.commit()
    print(f"Teams: {Team.query.count()}")


def seed_players():
    """Stars from players_stars.json + 18 generic numbered placeholders per team
    so dropdowns always have a full pool (~23 per side)."""
    stars_path = os.path.join(DATA_DIR, "players_stars.json")
    stars = json.load(open(stars_path, encoding="utf-8")) if os.path.exists(stars_path) else {}
    positions_cycle = ["GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD"]

    for team in Team.query.all():
        if team.players.count() > 0:
            continue
        team_stars = stars.get(team.code, [])
        used_numbers = set()
        for name_en, name_ar, pos, num in team_stars:
            p = Player(team_id=team.id, name_en=name_en, name_ar=name_ar,
                       position=pos, shirt_number=num)
            db.session.add(p)
            used_numbers.add(num)
        # fill remaining slots with placeholders so users can still pick a scorer
        next_num = 1
        for i in range(23 - len(team_stars)):
            while next_num in used_numbers:
                next_num += 1
            pos = positions_cycle[i % len(positions_cycle)]
            name_en = f"{team.name_en} #{next_num}"
            name_ar = f"{team.name_ar} رقم {next_num}"
            db.session.add(Player(team_id=team.id, name_en=name_en, name_ar=name_ar,
                                  position=pos, shirt_number=next_num))
            used_numbers.add(next_num)
            next_num += 1
    db.session.commit()
    print(f"Players: {Player.query.count()}")


def seed_matches():
    """If data/matches.json exists (from fetch_fifa_data.py), use that.
    Otherwise, generate a synthetic round-robin + knockout bracket so the app
    boots with something to predict."""
    if Match.query.count() > 0:
        print(f"Matches already seeded: {Match.query.count()}")
        return

    matches_file = os.path.join(DATA_DIR, "matches.json")
    if os.path.exists(matches_file):
        return _seed_matches_from_file(matches_file)

    groups = {}
    for team in Team.query.filter(Team.group_letter.isnot(None)).all():
        groups.setdefault(team.group_letter, []).append(team)

    start = datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)
    slot = start
    group_letters = sorted(groups.keys())

    # Group stage: round-robin within each group
    for letter in group_letters:
        teams = groups[letter]
        pairs = [(0, 1), (2, 3), (0, 2), (1, 3), (0, 3), (1, 2)]
        for i, j in pairs:
            if i >= len(teams) or j >= len(teams):
                continue
            m = Match(stage="group", group_letter=letter,
                      home_team_id=teams[i].id, away_team_id=teams[j].id,
                      kickoff_utc=slot,
                      venue=f"Venue (Group {letter})",
                      status="upcoming")
            db.session.add(m)
            slot += timedelta(hours=3)

    # Knockout placeholders (using top finishers from each group as a stand-in)
    # Real seeding happens after group stage; admin can edit teams later.
    db.session.commit()

    knockout_start = start + timedelta(days=18)
    slot = knockout_start
    # round of 32 — pair groups: A vs B winners etc. — just use first team per group as a placeholder
    firsts = [groups[L][0] for L in group_letters if groups[L]]
    knockout_pairs = []
    # Round of 32 (16 matches)
    for i in range(0, len(firsts) - 1, 2):
        knockout_pairs.append(("r32", firsts[i], firsts[i + 1]))
    # Round of 16
    seconds = [groups[L][1] for L in group_letters if len(groups[L]) > 1]
    for i in range(0, len(seconds) - 1, 2):
        knockout_pairs.append(("r16", seconds[i], seconds[i + 1]))
    # QF / SF / 3rd / Final — use top teams as placeholders, admin will edit
    knockout_pairs += [
        ("qf", firsts[0], firsts[1]),
        ("qf", firsts[2], firsts[3]),
        ("qf", firsts[4], firsts[5]),
        ("qf", firsts[6], firsts[7]),
        ("sf", firsts[0], firsts[2]),
        ("sf", firsts[4], firsts[6]),
        ("third", firsts[1], firsts[3]),
        ("final", firsts[0], firsts[4]),
    ]
    for stage, h, a in knockout_pairs:
        m = Match(stage=stage, group_letter=None,
                  home_team_id=h.id, away_team_id=a.id,
                  kickoff_utc=slot, venue=f"Venue ({stage})",
                  status="upcoming")
        db.session.add(m)
        slot += timedelta(hours=4)

    db.session.commit()
    print(f"Matches: {Match.query.count()}")


def _seed_matches_from_file(path):
    rows = json.load(open(path, encoding="utf-8"))
    code_to_team = {t.code: t for t in Team.query.all()}
    created = 0
    for r in rows:
        home = code_to_team.get(r["home_code"])
        away = code_to_team.get(r["away_code"])
        if not home or not away:
            continue
        ko = datetime.fromisoformat(r["kickoff_utc"].replace("Z", "+00:00"))
        m = Match(stage=r.get("stage", "group"),
                  group_letter=r.get("group_letter"),
                  home_team_id=home.id, away_team_id=away.id,
                  kickoff_utc=ko, venue=r.get("venue"),
                  status=r.get("status", "upcoming"),
                  home_score=r.get("home_score"),
                  away_score=r.get("away_score"))
        db.session.add(m)
        created += 1
    db.session.commit()
    print(f"Matches (from API): {created}")


def seed_admins():
    for username in ADMIN_USERNAMES:
        if User.query.filter_by(username=username).first():
            continue
        u = User(username=username, is_admin=True, must_change_password=True)
        u.set_password(DEFAULT_ADMIN_PASSWORD)
        db.session.add(u)
    # Superuser — has admin pages + the two extra pages (user details + points log)
    if not User.query.filter_by(username="superuser").first():
        su = User(username="superuser", is_admin=True, is_superuser=True,
                  must_change_password=True)
        su.set_password("super123")
        db.session.add(su)
    db.session.commit()
    print(f"Admins: {User.query.filter_by(is_admin=True).count()} (default password: {DEFAULT_ADMIN_PASSWORD}, must change on first login)")
    print("Superuser: username='superuser', password='super123' (must change on first login)")


def _ensure_schema():
    """Post-create_all migration. Runs after create_all + seed_teams so
    we know the matches table exists in the prod Postgres DB. Adds
    columns that older deploys may be missing.
    """
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    table_names = insp.get_table_names()
    if "matches" in table_names:
        cols = {c["name"] for c in insp.get_columns("matches")}
        if "winner_team_id" not in cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE matches ADD COLUMN winner_team_id INTEGER"))
            print("  + added matches.winner_team_id")


def main():
    with app.app_context():
        _wait_for_db()
        db.create_all()
        seed_teams()
        _ensure_schema()           # only after teams exist (FK target)
        seed_players()
        seed_matches()
        seed_admins()
        print("\nDone. Default admins: " + ", ".join(ADMIN_USERNAMES))
        print(f"Default password: {DEFAULT_ADMIN_PASSWORD}")


if __name__ == "__main__":
    main()
