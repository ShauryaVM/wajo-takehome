from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import active_account_ids, current_user
from app.models import AgentDecision, Email, Feedback, User

router = APIRouter(prefix="/analytics", tags=["analytics"])

ASKISH = {"ask_first", "escalate"}


@router.get("")
def analytics(db: Session = Depends(get_db), user: User = Depends(current_user)):
    ids = active_account_ids(db, user)
    if not ids:
        empty_days = []
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=13)
        for i in range(14):
            day = (start + timedelta(days=i)).date()
            empty_days.append({"day": day.isoformat(), "n": 0, "ask_rate": None})
        return {
            "totals": {"emails": 0, "decisions": 0, "safety_hits": 0, "overrides": 0, "pending": 0},
            "by_level": [],
            "by_status": [],
            "feedback": [],
            "accuracy": None,
            "override_rate": None,
            "ask_rate_by_day": empty_days,
        }
    emails_n = (
        db.query(func.count(Email.id))
        .filter(Email.user_id == user.id, Email.account_id.in_(ids))
        .scalar()
        or 0
    )
    decisions = (
        db.query(AgentDecision)
        .join(Email, Email.id == AgentDecision.email_id)
        .filter(Email.user_id == user.id, Email.account_id.in_(ids))
        .all()
    )
    by_level: dict[str, int] = {}
    by_status: dict[str, int] = {}
    safety_hits = 0
    pending = 0
    for d in decisions:
        by_level[d.autonomy_level] = by_level.get(d.autonomy_level, 0) + 1
        by_status[d.status] = by_status.get(d.status, 0) + 1
        if d.safety_hit:
            safety_hits += 1
        if d.status in {"pending", "escalated"} and d.autonomy_level in ASKISH:
            pending += 1

    fbs = (
        db.query(Feedback)
        .join(AgentDecision, AgentDecision.id == Feedback.decision_id)
        .join(Email, Email.id == AgentDecision.email_id)
        .filter(Email.user_id == user.id, Email.account_id.in_(ids))
        .all()
    )
    fb_counts: dict[str, int] = {}
    for f in fbs:
        fb_counts[f.feedback_type] = fb_counts.get(f.feedback_type, 0) + 1
    good = fb_counts.get("good", 0)
    corrections = sum(fb_counts.get(k, 0) for k in ("too_aggressive", "too_cautious", "wrong_action"))
    judged = good + corrections
    accuracy = (good / judged) if judged else None

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=13)
    ask_rate_by_day = []
    for i in range(14):
        day = (start + timedelta(days=i)).date()
        day_rows = [
            d
            for d in decisions
            if d.created_at.astimezone(timezone.utc).date() == day
        ]
        n = len(day_rows)
        asks = sum(1 for d in day_rows if d.autonomy_level in ASKISH)
        ask_rate_by_day.append(
            {
                "day": day.isoformat(),
                "n": n,
                "ask_rate": (asks / n) if n else None,
            }
        )

    override_rate = None
    if decisions:
        override_rate = by_status.get("overridden", 0) / len(decisions)

    return {
        "totals": {
            "emails": emails_n,
            "decisions": len(decisions),
            "safety_hits": safety_hits,
            "overrides": by_status.get("overridden", 0),
            "pending": pending,
        },
        "by_level": [{"level": k, "n": v} for k, v in by_level.items()],
        "by_status": [{"status": k, "n": v} for k, v in by_status.items()],
        "feedback": [{"type": k, "n": v} for k, v in fb_counts.items()],
        "accuracy": accuracy,
        "override_rate": override_rate,
        "ask_rate_by_day": ask_rate_by_day,
    }
