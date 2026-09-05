from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.autonomy import less_cautious, more_cautious, rank
from app.classifier import guess_category, sender_domain
from app.models import AgentDecision, Email, Feedback, Preference

HARD_HITS = {"money", "prompt_injection", "delete", "forward_external"}
ASK_FLOOR_HITS = {"send", "unsubscribe"}
ASK_FLOOR_ACTIONS = {"send", "draft_reply", "unsubscribe"}


def _target_level(decision: AgentDecision, feedback_type: str, corrected: str | None) -> str:
    if feedback_type == "too_aggressive":
        target = more_cautious(decision.autonomy_level)
    elif feedback_type == "too_cautious":
        target = less_cautious(decision.autonomy_level)
    elif feedback_type == "wrong_action":
        target = corrected or more_cautious(decision.autonomy_level)
    else:
        target = decision.autonomy_level
        if corrected:
            target = corrected

    if decision.safety_hit in HARD_HITS or decision.action_type in {"delete", "forward"}:
        if rank(target) < rank("escalate"):
            target = "escalate"
    elif decision.safety_hit in ASK_FLOOR_HITS or decision.action_type in ASK_FLOOR_ACTIONS:
        if rank(target) < rank("ask_first"):
            target = "ask_first"
    return target


def _upsert_pref(db: Session, user_id: int, ptype: str, value: str, target: str, good: bool) -> None:
    if not value:
        return
    row = (
        db.query(Preference)
        .filter(
            Preference.user_id == user_id,
            Preference.pattern_type == ptype,
            Preference.pattern_value == value,
        )
        .one_or_none()
    )
    if row is None:
        row = Preference(
            user_id=user_id,
            pattern_type=ptype,
            pattern_value=value[:255],
            preferred_autonomy=target,
            confidence=0.45 if good else 0.55,
            sample_count=1,
        )
        db.add(row)
        return

    if row.preferred_autonomy != target:
        row.preferred_autonomy = target
        row.confidence = min(0.95, max(0.35, row.confidence * 0.7 + 0.25))
    else:
        bump = 0.07 if good else 0.11
        row.confidence = min(0.95, row.confidence + bump)
    row.sample_count += 1
    row.updated_at = datetime.now(timezone.utc)


def record_feedback(
    db: Session,
    decision: AgentDecision,
    feedback_type: str,
    corrected_autonomy_level: str | None = None,
    user_comment: str | None = None,
) -> Feedback:
    fb = Feedback(
        decision_id=decision.id,
        feedback_type=feedback_type,
        corrected_autonomy_level=corrected_autonomy_level,
        user_comment=user_comment,
    )
    db.add(fb)

    email = decision.email
    if email is None:
        email = db.query(Email).filter(Email.id == decision.email_id).one()

    target = _target_level(decision, feedback_type, corrected_autonomy_level)
    good = feedback_type == "good"
    domain = sender_domain(email.sender)
    category = (decision.proposed_action or {}).get("category") or guess_category(
        email.sender, email.subject, email.body_text, list(email.labels or [])
    )
    _upsert_pref(db, email.user_id, "sender_domain", domain, target, good)
    _upsert_pref(db, email.user_id, "category", category, target, good)
    db.flush()
    return fb


def preferences_for(db: Session, user_id: int, sender: str, category: str) -> list[dict]:
    domain = sender_domain(sender)
    rows = db.query(Preference).filter(Preference.user_id == user_id).all()
    scored = []
    for r in rows:
        score = 0.0
        if r.pattern_type == "sender_domain" and r.pattern_value == domain:
            score = 2.0 + r.confidence
        elif r.pattern_type == "category" and r.pattern_value == category:
            score = 1.0 + r.confidence
        elif r.confidence >= 0.7:
            score = 0.2 + r.confidence
        if score:
            scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for _, r in scored[:8]:
        out.append(
            {
                "pattern_type": r.pattern_type,
                "pattern_value": r.pattern_value,
                "preferred_autonomy": r.preferred_autonomy,
                "confidence": r.confidence,
                "sample_count": r.sample_count,
            }
        )
    return out


def similar_decisions(db: Session, user_id: int, sender: str, category: str, limit: int = 5) -> list[dict]:
    domain = sender_domain(sender)
    q = (
        db.query(AgentDecision, Email, Feedback)
        .join(Email, Email.id == AgentDecision.email_id)
        .outerjoin(Feedback, Feedback.decision_id == AgentDecision.id)
        .filter(Email.user_id == user_id)
        .order_by(AgentDecision.created_at.desc())
        .limit(40)
    )
    ranked = []
    for decision, email, fb in q.all():
        score = 0
        if sender_domain(email.sender) == domain:
            score += 3
        cat = (decision.proposed_action or {}).get("category")
        if cat == category:
            score += 2
        if fb:
            score += 1
        if score:
            ranked.append(
                (
                    score,
                    {
                        "sender": email.sender,
                        "subject": email.subject,
                        "autonomy_level": decision.autonomy_level,
                        "feedback": fb.feedback_type if fb else None,
                    },
                )
            )
    ranked.sort(key=lambda x: x[0], reverse=True)
    seen = []
    out = []
    for _, item in ranked:
        key = (item["sender"], item["subject"])
        if key in seen:
            continue
        seen.append(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out
