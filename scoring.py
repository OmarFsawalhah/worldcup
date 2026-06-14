"""Auto-scoring logic. Pure function called when admin saves a match result
or a trivia question's correct answer."""

import json

from models import db, Match, Prediction, TriviaQuestion, TriviaAnswer

POINTS_EXACT_SCORE = 3
POINTS_FIRST_SCORER = 3
POINTS_MOTM = 3
POINTS_TRIVIA = 3
POINTS_WINNER_BONUS = 1


def _winner_side(home, away):
    if home > away:
        return "home"
    if away > home:
        return "away"
    return "draw"


def score_match(match: Match) -> None:
    """Recompute points_awarded for every prediction on this match.

    Safe to call repeatedly; overwrites prior values."""
    if match.home_score is None or match.away_score is None:
        return

    actual_winner = _winner_side(match.home_score, match.away_score)
    actual_first = match.first_scorer_id
    actual_motm = match.motm_id

    for p in match.predictions:
        pts = 0
        if p.home_score == match.home_score and p.away_score == match.away_score:
            pts += POINTS_EXACT_SCORE
        else:
            # winner-only consolation
            if _winner_side(p.home_score, p.away_score) == actual_winner:
                pts += POINTS_WINNER_BONUS
        if actual_first is not None and p.first_scorer_id == actual_first:
            pts += POINTS_FIRST_SCORER
        if actual_motm is not None and p.motm_id == actual_motm:
            pts += POINTS_MOTM
        p.points_awarded = pts

    # also score trivia answers attached to this match (if question + correct answer set)
    if match.trivia is not None:
        score_trivia(match.trivia)

    db.session.commit()


def score_trivia(question: TriviaQuestion) -> None:
    for ans in question.answers:
        ans.points_awarded = POINTS_TRIVIA if ans.choice_index == question.correct_index else 0
    db.session.commit()


def user_total_points(user_id: int) -> int:
    from models import User
    pred_total = db.session.query(db.func.coalesce(db.func.sum(Prediction.points_awarded), 0)) \
        .filter(Prediction.user_id == user_id).scalar() or 0
    triv_total = db.session.query(db.func.coalesce(db.func.sum(TriviaAnswer.points_awarded), 0)) \
        .filter(TriviaAnswer.user_id == user_id).scalar() or 0
    user = db.session.get(User, user_id)
    bonus = user.bonus_points if user else 0
    return int(pred_total) + int(triv_total) + int(bonus)


def user_exact_score_hits(user_id: int) -> int:
    return db.session.query(db.func.count(Prediction.id)) \
        .join(Match, Prediction.match_id == Match.id) \
        .filter(Prediction.user_id == user_id) \
        .filter(Match.home_score == Prediction.home_score) \
        .filter(Match.away_score == Prediction.away_score).scalar() or 0


def prediction_breakdown(prediction, match) -> dict:
    """Per-source point breakdown for a prediction on a finished match.
    Returns a dict the profile page can render as a detail row.
    All numeric fields are 0 if the match isn't finished yet."""
    out = {
        "exact": 0, "winner": 0, "first_scorer": 0, "motm": 0,
        "exact_hit": False, "winner_hit": False,
        "first_scorer_hit": False, "motm_hit": False,
        "total": prediction.points_awarded,
        "result_pending": match.home_score is None or match.away_score is None,
    }
    if out["result_pending"]:
        return out

    if prediction.home_score == match.home_score and prediction.away_score == match.away_score:
        out["exact"] = POINTS_EXACT_SCORE
        out["exact_hit"] = True
    else:
        if _winner_side(prediction.home_score, prediction.away_score) == _winner_side(match.home_score, match.away_score):
            out["winner"] = POINTS_WINNER_BONUS
            out["winner_hit"] = True
    if match.first_scorer_id is not None and prediction.first_scorer_id == match.first_scorer_id:
        out["first_scorer"] = POINTS_FIRST_SCORER
        out["first_scorer_hit"] = True
    if match.motm_id is not None and prediction.motm_id == match.motm_id:
        out["motm"] = POINTS_MOTM
        out["motm_hit"] = True
    return out
