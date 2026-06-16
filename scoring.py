"""Auto-scoring logic. Pure function called when admin saves a match result."""

from models import db, Match, Prediction

# Primary prediction: winner / draw
POINTS_WINNER = 3
# Bonus on top of winner: also picked the exact score
POINTS_EXACT_BONUS = 2
POINTS_FIRST_SCORER = 3
POINTS_MOTM = 3


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
        # Primary: did they pick the right winner / draw?
        winner_hit = p.winner_prediction == actual_winner
        if winner_hit:
            pts += POINTS_WINNER
            # Bonus: ALSO predicted exact score (only counts when winner is right too)
            if (p.home_score is not None and p.away_score is not None
                    and p.home_score == match.home_score and p.away_score == match.away_score):
                pts += POINTS_EXACT_BONUS
        if actual_first is not None and p.first_scorer_id == actual_first:
            pts += POINTS_FIRST_SCORER
        if actual_motm is not None and p.motm_id == actual_motm:
            pts += POINTS_MOTM
        p.points_awarded = pts

    db.session.commit()


def user_total_points(user_id: int) -> int:
    from models import User
    pred_total = db.session.query(db.func.coalesce(db.func.sum(Prediction.points_awarded), 0)) \
        .filter(Prediction.user_id == user_id).scalar() or 0
    user = db.session.get(User, user_id)
    bonus = user.bonus_points if user else 0
    return int(pred_total) + int(bonus)


def user_exact_score_hits(user_id: int) -> int:
    return db.session.query(db.func.count(Prediction.id)) \
        .join(Match, Prediction.match_id == Match.id) \
        .filter(Prediction.user_id == user_id) \
        .filter(Match.home_score == Prediction.home_score) \
        .filter(Match.away_score == Prediction.away_score).scalar() or 0


def prediction_breakdown(prediction, match) -> dict:
    """Per-source point breakdown for a prediction on a finished match.
    Returns a dict the profile page can render as a detail row."""
    out = {
        "winner": 0, "exact": 0, "first_scorer": 0, "motm": 0,
        "winner_hit": False, "exact_hit": False,
        "first_scorer_hit": False, "motm_hit": False,
        "predicted_exact": prediction.home_score is not None and prediction.away_score is not None,
        "total": prediction.points_awarded,
        "result_pending": match.home_score is None or match.away_score is None,
    }
    if out["result_pending"]:
        return out

    actual_winner = _winner_side(match.home_score, match.away_score)
    if prediction.winner_prediction == actual_winner:
        out["winner"] = POINTS_WINNER
        out["winner_hit"] = True
        if (out["predicted_exact"]
                and prediction.home_score == match.home_score
                and prediction.away_score == match.away_score):
            out["exact"] = POINTS_EXACT_BONUS
            out["exact_hit"] = True
    if match.first_scorer_id is not None and prediction.first_scorer_id == match.first_scorer_id:
        out["first_scorer"] = POINTS_FIRST_SCORER
        out["first_scorer_hit"] = True
    if match.motm_id is not None and prediction.motm_id == match.motm_id:
        out["motm"] = POINTS_MOTM
        out["motm_hit"] = True
    return out
