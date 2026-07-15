"""Dump every row from every table in the current DATABASE_URL to a
single JSON file, suitable for restoring into a fresh database with
`python scripts/restore_db.py <dump.json>`.

Why JSON instead of `pg_dump`? `pg_dump` isn't always installed locally
and its binary output is Postgres-version-specific. JSON is portable
across Postgres versions and easy to inspect.

Usage:
    set DATABASE_URL=postgresql://user:pass@host/db
    python scripts/backup_db.py backup.json

Or pass the URL inline:
    python scripts/backup_db.py backup.json --url postgresql://...
"""
import argparse
import json
import os
import sys
from datetime import datetime, date
from decimal import Decimal

# Allow running from project root
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from sqlalchemy import inspect

from app import app
from models import db


# Map of table_name -> model class. Update if you add new models.
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


def _default(o):
    """JSON encoder for things SQLAlchemy returns that aren't JSON-native."""
    if isinstance(o, datetime):
        return {"__type__": "datetime", "iso": o.isoformat()}
    if isinstance(o, date):
        return {"__type__": "date", "iso": o.isoformat()}
    if isinstance(o, Decimal):
        return {"__type__": "decimal", "value": str(o)}
    if isinstance(o, bytes):
        return {"__type__": "bytes", "b64": o.hex()}
    raise TypeError(f"Cannot serialize {type(o)}")


def _row_to_dict(row):
    """Dump a SQLAlchemy ORM row to a plain dict for JSON. Only includes
    columns that are actually set (i.e. not the lazy-loaded relationships)."""
    d = {}
    for col in row.__table__.columns:
        v = getattr(row, col.name)
        if v is None:
            d[col.name] = None
        else:
            d[col.name] = v
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output", help="Path to write the JSON dump (e.g. backup.json)")
    ap.add_argument("--url", help="Override DATABASE_URL env var for this run")
    args = ap.parse_args()

    if args.url:
        os.environ["DATABASE_URL"] = args.url

    with app.app_context():
        # Test the connection early so a bad URL doesn't leave an empty file.
        insp = inspect(db.engine)
        tables = insp.get_table_names()
        if not tables:
            print("ERROR: connected, but no tables found. Wrong database?",
                  file=sys.stderr)
            sys.exit(2)

        dump = {"_meta": {"app": "worldcup-predictor", "version": 1,
                          "created_at": datetime.utcnow().isoformat() + "Z",
                          "tables": sorted(tables)},
                "tables": {}}

        for table in sorted(tables):
            model_name = TABLE_MODEL_MAP.get(table)
            if not model_name:
                print(f"  SKIP {table} (no model mapping)")
                continue
            model = sys.modules["models"].__dict__.get(model_name)
            if model is None:
                print(f"  SKIP {table} (model {model_name} not importable)")
                continue
            rows = db.session.query(model).all()
            dump["tables"][table] = [_row_to_dict(r) for r in rows]
            print(f"  {table:25s} {len(rows):>6d} rows")

        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(dump, fh, default=_default, ensure_ascii=False, indent=2)
        print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
