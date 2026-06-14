from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required

from models import db, User
from i18n import t

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            flash(t("auth.invalid"), "error")
            return render_template("login.html"), 401
        login_user(user)
        return redirect(url_for("public.dashboard"))
    return render_template("login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("password_confirm") or ""
        if not username or not password:
            flash(t("auth.invalid"), "error")
            return render_template("register.html"), 400
        if password != confirm:
            flash(t("auth.mismatch"), "error")
            return render_template("register.html"), 400
        if User.query.filter_by(username=username).first():
            flash(t("auth.taken"), "error")
            return render_template("register.html"), 400
        user = User(username=username, is_admin=False)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for("public.dashboard"))
    return render_template("register.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    from flask_login import current_user
    if request.method == "POST":
        current_pw = request.form.get("current_password") or ""
        new_pw = request.form.get("new_password") or ""
        confirm = request.form.get("new_password_confirm") or ""
        if not current_user.check_password(current_pw):
            flash(t("auth.invalid_current_password"), "error")
            return render_template("change_password.html"), 400
        if len(new_pw) < 6:
            flash(t("auth.password_too_short"), "error")
            return render_template("change_password.html"), 400
        if new_pw != confirm:
            flash(t("auth.mismatch"), "error")
            return render_template("change_password.html"), 400
        current_user.set_password(new_pw)
        current_user.must_change_password = False
        db.session.commit()
        flash(t("auth.password_changed"), "success")
        return redirect(url_for("public.dashboard"))
    return render_template("change_password.html")
