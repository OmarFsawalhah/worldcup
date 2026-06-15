import os
from flask import Flask, redirect, url_for, session
from flask_login import LoginManager, current_user

from models import db, User
from i18n import load_translations, t, current_lang, is_rtl


def _normalize_db_url(url: str) -> str:
    # Render gives postgres:// but SQLAlchemy 2.x wants postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _flag_url(team, size=80):
    """Return a CDN URL for the team's flag. Decodes the regional-indicator
    emoji stored in Team.flag_emoji back into a 2-letter ISO code.
    Falls back to a generic UN flag if decoding fails."""
    emoji = (team.flag_emoji or "").strip()
    code = ""
    for ch in emoji:
        c = ord(ch)
        # Regional Indicator Symbol Letter A..Z
        if 0x1F1E6 <= c <= 0x1F1FF:
            code += chr(ord("A") + c - 0x1F1E6)
    code = code.lower()
    if len(code) != 2:
        return f"https://flagcdn.com/w{size}/un.png"  # neutral fallback
    return f"https://flagcdn.com/w{size}/{code}.png"


def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    db_url = os.environ.get("DATABASE_URL", "sqlite:///worldcup.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_db_url(db_url)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    load_translations(app)

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(uid):
        return db.session.get(User, int(uid))

    # Jinja helpers
    app.jinja_env.globals["t"] = t
    app.jinja_env.globals["current_lang"] = current_lang
    app.jinja_env.globals["is_rtl"] = is_rtl
    app.jinja_env.globals["flag_url"] = _flag_url

    from routes.auth import bp as auth_bp
    from routes.public import bp as public_bp
    from routes.admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)

    # Force users with must_change_password=True to set a new one before they
    # can use the rest of the app.
    @app.before_request
    def _enforce_password_change():
        from flask import request
        if not current_user.is_authenticated:
            return None
        if not getattr(current_user, "must_change_password", False):
            return None
        allowed = {"auth.change_password", "auth.logout", "static", "set_lang"}
        if request.endpoint in allowed:
            return None
        return redirect(url_for("auth.change_password"))

    @app.route("/lang/<code>")
    def set_lang(code):
        if code in ("en", "ar"):
            session["lang"] = code
        return redirect(request_referrer_or_root())

    with app.app_context():
        db.create_all()
        _auto_migrate()

    return app


def _auto_migrate():
    """Add columns added in later code revisions if they're missing.
    Lightweight — just handles the small additive changes we've made."""
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    if "trivia_questions" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("trivia_questions")}
        if "author_id" not in cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE trivia_questions ADD COLUMN author_id INTEGER"))
    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        # Use DEFAULT FALSE (not 0) so the ALTER works on both Postgres and SQLite.
        bool_default = "FALSE"
        if "must_change_password" not in cols:
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT {bool_default} NOT NULL"))
        if "bonus_points" not in cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN bonus_points INTEGER DEFAULT 0 NOT NULL"))
        if "is_superuser" not in cols:
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN is_superuser BOOLEAN DEFAULT {bool_default} NOT NULL"))
    if "matches" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("matches")}
        if "calculated_by_id" not in cols:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE matches ADD COLUMN calculated_by_id INTEGER"))
    if "predictions" in insp.get_table_names():
        cols_info = {c["name"]: c for c in insp.get_columns("predictions")}
        cols = set(cols_info.keys())
        # Loosen NOT NULL on winner_prediction
        if "winner_prediction" in cols:
            is_not_null = not cols_info["winner_prediction"].get("nullable", True)
            if is_not_null:
                if db.engine.dialect.name == "postgresql":
                    try:
                        with db.engine.begin() as conn:
                            conn.execute(text("ALTER TABLE predictions ALTER COLUMN winner_prediction DROP NOT NULL"))
                    except Exception:
                        pass
                elif db.engine.dialect.name == "sqlite":
                    # SQLite doesn't support ALTER COLUMN — rebuild table preserving data
                    try:
                        col_names = [c["name"] for c in insp.get_columns("predictions")]
                        cols_sql = ", ".join(col_names)
                        with db.engine.begin() as conn:
                            conn.execute(text("ALTER TABLE predictions RENAME TO predictions_old"))
                        db.create_all()
                        with db.engine.begin() as conn:
                            conn.execute(text(f"INSERT INTO predictions ({cols_sql}) SELECT {cols_sql} FROM predictions_old"))
                            conn.execute(text("DROP TABLE predictions_old"))
                    except Exception as e:
                        # Best-effort: leave schema as-is
                        print(f"[migrate] SQLite predictions rebuild failed: {e}")
        if "winner_prediction" not in cols:
            with db.engine.begin() as conn:
                row_count = conn.execute(text("SELECT COUNT(*) FROM predictions")).scalar() or 0
                if row_count == 0:
                    # No data — drop and let create_all rebuild with the new schema
                    conn.execute(text("DROP TABLE predictions"))
                else:
                    # Data present — add column + loosen NOT NULL where supported
                    conn.execute(text("ALTER TABLE predictions ADD COLUMN winner_prediction VARCHAR(8)"))
                    if db.engine.dialect.name == "postgresql":
                        conn.execute(text("ALTER TABLE predictions ALTER COLUMN home_score DROP NOT NULL"))
                        conn.execute(text("ALTER TABLE predictions ALTER COLUMN away_score DROP NOT NULL"))
            db.create_all()


def request_referrer_or_root():
    from flask import request
    return request.referrer or "/"


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
