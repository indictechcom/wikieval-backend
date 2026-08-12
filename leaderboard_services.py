"""
Service layer for contest leaderboards.
Aggregates submission data per participant for a given contest.
"""

from model import db, Contest, Submission, User


def get_leaderboard(contest_id):
    """
    Build a ranked leaderboard for a contest.

    Ranking is based on total score (sum of scores across all reviewed
    submissions by that participant), descending. Participants with no
    reviewed submissions yet still appear, with total_score=0.

    Returns:
        dict: {
            "contest_id": int,
            "contest_name": str,
            "leaderboard": [
                {
                    "rank": int,
                    "user_id": int,
                    "username": str,
                    "total_score": float,
                    "submission_count": int,
                    "reviewed_count": int,
                    "pending_count": int,
                },
                ...
            ]
        }
    """
    contest = db.session.get(Contest, contest_id)
    if not contest:
        raise ValueError("Contest not found")

    submissions = Submission.query.filter_by(contest_id=contest_id).all()

    # Aggregate per participant
    stats = {}
    for sub in submissions:
        uid = sub.user_id
        if uid not in stats:
            stats[uid] = {
                "user_id": uid,
                "username": sub.participant.username if sub.participant else None,
                "total_score": 0.0,
                "submission_count": 0,
                "reviewed_count": 0,
                "pending_count": 0,
            }

        stats[uid]["submission_count"] += 1

        if sub.status == "reviewed":
            stats[uid]["reviewed_count"] += 1
            stats[uid]["total_score"] += sub.score or 0.0
        elif sub.status == "pending_review":
            stats[uid]["pending_count"] += 1
        # 'rejected' submissions count toward submission_count but not
        # reviewed/pending, since they never entered jury review.

    # Sort by total_score descending, assign ranks
    ranked = sorted(stats.values(), key=lambda s: s["total_score"], reverse=True)
    for i, entry in enumerate(ranked, start=1):
        entry["rank"] = i

    return {
        "contest_id": contest.id,
        "contest_name": contest.name,
        "leaderboard": ranked,
    }