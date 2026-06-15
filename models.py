from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    bonus_points = db.Column(db.Integer, default=0, nullable=False)  # manual admin adjustment
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    predictions = db.relationship("Prediction", backref="user", lazy="dynamic")
    trivia_answers = db.relationship("TriviaAnswer", backref="user", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Team(db.Model):
    __tablename__ = "teams"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(3), unique=True, nullable=False)
    name_en = db.Column(db.String(64), nullable=False)
    name_ar = db.Column(db.String(64), nullable=False)
    flag_emoji = db.Column(db.String(8), nullable=False, default="")
    group_letter = db.Column(db.String(1), nullable=True)

    players = db.relationship("Player", backref="team", lazy="dynamic")

    def name(self, lang="en"):
        return self.name_ar if lang == "ar" else self.name_en


class Player(db.Model):
    __tablename__ = "players"
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False)
    name_en = db.Column(db.String(96), nullable=False)
    name_ar = db.Column(db.String(96), nullable=False)
    position = db.Column(db.String(16), nullable=True)
    shirt_number = db.Column(db.Integer, nullable=True)

    def name(self, lang="en"):
        return self.name_ar if lang == "ar" else self.name_en


class Match(db.Model):
    __tablename__ = "matches"
    id = db.Column(db.Integer, primary_key=True)
    stage = db.Column(db.String(16), nullable=False)  # group/r32/r16/qf/sf/third/final
    group_letter = db.Column(db.String(1), nullable=True)
    home_team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False)
    away_team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False)
    kickoff_utc = db.Column(db.DateTime, nullable=False)
    venue = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(16), nullable=False, default="upcoming")
    home_score = db.Column(db.Integer, nullable=True)
    away_score = db.Column(db.Integer, nullable=True)
    first_scorer_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=True)
    motm_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=True)
    calculated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    home_team = db.relationship("Team", foreign_keys=[home_team_id])
    away_team = db.relationship("Team", foreign_keys=[away_team_id])
    first_scorer = db.relationship("Player", foreign_keys=[first_scorer_id])
    motm = db.relationship("Player", foreign_keys=[motm_id])
    calculated_by = db.relationship("User", foreign_keys=[calculated_by_id])
    predictions = db.relationship("Prediction", backref="match", lazy="dynamic", cascade="all, delete-orphan")
    trivia = db.relationship("TriviaQuestion", backref="match", uselist=False, cascade="all, delete-orphan")

    def kickoff_aware(self):
        ko = self.kickoff_utc
        if ko.tzinfo is None:
            ko = ko.replace(tzinfo=timezone.utc)
        return ko

    def is_locked(self):
        return utcnow() >= self.kickoff_aware()

    def has_finished(self):
        return self.status == "finished" and self.home_score is not None

    def trivia_open(self):
        # Trivia is part of the prediction wizard now — answerable any time
        # before kickoff (no longer gated to the T-1h window).
        if not self.trivia:
            return False
        return utcnow() < self.kickoff_aware()


class Prediction(db.Model):
    __tablename__ = "predictions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), nullable=False)
    # Primary prediction: 'home' / 'draw' / 'away' (nullable — user may skip in the wizard)
    winner_prediction = db.Column(db.String(8), nullable=True)
    # Optional bonus prediction: exact final score
    home_score = db.Column(db.Integer, nullable=True)
    away_score = db.Column(db.Integer, nullable=True)
    first_scorer_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=True)
    motm_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=True)
    points_awarded = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    first_scorer = db.relationship("Player", foreign_keys=[first_scorer_id])
    motm = db.relationship("Player", foreign_keys=[motm_id])

    __table_args__ = (db.UniqueConstraint("user_id", "match_id", name="uq_user_match"),)


class TriviaQuestion(db.Model):
    __tablename__ = "trivia_questions"
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), unique=True, nullable=False)
    question_ar = db.Column(db.Text, nullable=False)
    choices_json = db.Column(db.Text, nullable=False)  # JSON list of strings
    correct_index = db.Column(db.Integer, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    author = db.relationship("User", foreign_keys=[author_id])
    answers = db.relationship("TriviaAnswer", backref="question", lazy="dynamic", cascade="all, delete-orphan")


class TriviaAnswer(db.Model):
    __tablename__ = "trivia_answers"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("trivia_questions.id"), nullable=False)
    choice_index = db.Column(db.Integer, nullable=False)
    points_awarded = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("user_id", "question_id", name="uq_user_question"),)


class QuestionBank(db.Model):
    """Global pool of trivia questions. Rows are deleted the moment a question
    is assigned to a user (so the same question is never given twice)."""
    __tablename__ = "question_bank"
    id = db.Column(db.Integer, primary_key=True)
    question_ar = db.Column(db.Text, nullable=False)
    choices_json = db.Column(db.Text, nullable=False)        # JSON list of strings
    correct_index = db.Column(db.Integer, nullable=False)
    difficulty = db.Column(db.String(16), nullable=True)     # 'medium'/'hard'/'very_hard' (optional)


class MatchTrivia(db.Model):
    """One question randomly assigned to (user, match). Snapshots the question
    so it survives even after the QuestionBank row is deleted. Holds the user's
    answer + points (scored instantly when answer is submitted)."""
    __tablename__ = "match_trivia"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), nullable=False)
    question_ar = db.Column(db.Text, nullable=False)
    choices_json = db.Column(db.Text, nullable=False)
    correct_index = db.Column(db.Integer, nullable=False)
    choice_index = db.Column(db.Integer, nullable=True)      # user's answer (null until submitted)
    points_awarded = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    match = db.relationship("Match", foreign_keys=[match_id])

    __table_args__ = (db.UniqueConstraint("user_id", "match_id", name="uq_user_match_trivia"),)
