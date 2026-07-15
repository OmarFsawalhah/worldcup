"""Restore a JSON dump produced by `scripts/backup_db.py` into the
current DATABASE_URL. Truncates the target tables first, then inserts
the dumped rows. Safe to re-run.

Usage:
    set DATABASE_URL=postgresql://user:pass@host/db
    python scripts/restore_db.py backup.json

Drops and recreates sequences (for the auto-increment IDs) so the
sequence doesn't collide with manually-set IDs.
"""
import argparse
import json
import os
import sys
from datetime import datetime, date
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from sqlalchemy import inspect, text

from app import app
from models import db


TABLE_MODEL_MAP = {
    "users": "User",
    "teams": "Team",
    "players": "Player",
    "matches": "Match",
    "predictions": "Prediction",
    "notifications": "Notification",
    "push_subscriptions": "PushSubscription",
    "trivia_questions": "TriviaQuestion",
    "trivia_answers": "TriviaAnswer",
    "question_bank": "QuestionBank",
    "match_trivia": "MatchTrivia",
}


def _from_json(o):
    """Inverse of backup_db._default."""
    if isinstance(o, dict) and "__type__" in o:
        t = o["__type__"]
        if t == "datetime":
            return datetime.fromisoformat(o["iso"])
        if t == "date":
            return date.fromisoformat(o["iso"])
        if t == "decimal":
            return Decimal(o["value"])
        if t == "bytes":
            return bytes.fromhex(o["b64"])
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="Path to the JSON dump from backup_db.py")
    ap.add_argument("--url", help="Override DATABASE_URL env var for this run")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the confirmation prompt")
    args = ap.parse_args()

    if args.url:
        os.environ["DATABASE_URL"] = args.url

    with open(args.input, encoding="utf-8") as fh:
        dump = json.load(fh, object_hook=_from_json)

    tables = dump.get("tables", {})
    if not tables:
        print("ERROR: dump contains no tables", file=sys.stderr)
        sys.exit(2)

    if not args.yes:
        print(f"This will TRUNCATE every table in the current database and")
        print(f"restore {len(tables)} tables from {args.input}.")
        print(f"Target: {os.environ.get('DATABASE_URL', '(default)')}")
        resp = input("Type 'yes' to continue: ")
        if resp.strip().lower() != "yes":
            print("Aborted.")
            return

    with app.app_context():
        insp = inspect(db.engine)
        existing = set(insp.get_table_names())
        dialect = db.engine.dialect.name

        # Truncate in reverse dependency order. Postgres: disable FK checks
        # via session_replication_role, then TRUNCATE … CASCADE. SQLite: no
        # such knob, so delete in dependency order and turn off FKs instead.
        with db.engine.begin() as conn:
            if dialect == "postgresql":
                conn.execute(text("SET session_replication_role = 'replica'"))
                for t in sorted(tables.keys()):
                    if t in existing:
                        conn.execute(text(f'TRUNCATE TABLE "{t}" RESTART IDENTITY CASCADE'))
                conn.execute(text("SET session_replication_role = 'origin'"))
            else:
                conn.execute(text("PRAGMA foreign_keys = OFF"))
                for t in sorted(tables.keys()):
                    if t in existing:
                        conn.execute(text(f'DELETE FROM "{t}"'))
                        # reset sqlite_sequence so auto-increment IDs start
                        # fresh; table only exists if there are autoincrement
                        # columns in the DB.
                        seq_exists = conn.execute(text(
                            "SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='sqlite_sequence'"
                        )).scalar()
                        if seq_exists:
                            conn.execute(text(
                                "DELETE FROM sqlite_sequence WHERE name = :t"
                            ), {"t": t})
                conn.execute(text("PRAGMA foreign_keys = ON"))

        # Now insert
        for table, rows in tables.items():
            model_name = TABLE_MODEL_MAP.get(table)
            if not model_name:
                print(f"  SKIP {table} (no model mapping)")
                continue
            model = sys.modules["models"].__dict__.get(model_name)
            if model is None:
                print(f"  SKIP {table} (model {model_name} not importable)")
                continue
            if not rows:
                print(f"  {table:25s}     0 rows (empty)")
                continue
            # SQLAlchemy's bulk insert is faster and survives simple types.
            db.session.bulk_insert_mappings(model, rows)
            print(f"  {table:25s} {len(rows):>6d} rows restored")
        db.session.commit()

        print("\nDone. Restart the app and verify.")


if __name__ == "__main__":
    main()
