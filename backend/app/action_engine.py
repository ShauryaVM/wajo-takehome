from datetime import datetime, timezone
import logging
import re

from sqlalchemy.orm import Session

from app.classifier import Classification, classify_email
from app.models import AgentDecision, Email, EmailAccount, SafetyRule
from app.providers.base import SendPayload
from app.providers.router import persist_refreshed_tokens, provider_for
from app.safety_guard import apply_safety, user_rule_applies

log = logging.getLogger("steward.actions")


def _addr(sender: str) -> str:
    m = re.search(r"<([^>]+)>", sender or "")
    return (m.group(1) if m else sender).strip()


def extra_floors(
    db: Session,
    user_id: int,
    sender: str = "",
    action_type: str = "",
) -> list[tuple[str, str]]:
    rows = (
        db.query(SafetyRule)
        .filter(SafetyRule.user_id == user_id, SafetyRule.is_system.is_(False))
        .all()
    )
    out: list[tuple[str, str]] = []
    for r in rows:
        if user_rule_applies(r.rule_type, r.action_type, sender, action_type):
            out.append((r.label or r.rule_type, r.min_autonomy_level))
    return out


def run_action(account: EmailAccount, email: Email, action_type: str, clf: Classification) -> dict:
    provider = provider_for(account)
    mid = email.provider_message_id
    result: dict = {"action": action_type}

    if action_type == "archive":
        provider.archive(mid)
    elif action_type == "label":
        provider.apply_label(mid, clf.label or clf.category or "steward")
        result["label"] = clf.label or clf.category
    elif action_type == "unsubscribe":
        unsub = (email.raw_json or {}).get("list_unsubscribe")
        provider.unsubscribe(mid, unsub)
    elif action_type == "draft_reply":
        to = _addr(email.sender)
        subj = email.subject if email.subject.lower().startswith("re:") else f"Re: {email.subject}"
        draft_id = provider.create_draft(
            SendPayload(to=[to], subject=subj, body=clf.draft or "", in_reply_to=mid)
        )
        result["draft_id"] = draft_id
    elif action_type in {"none", "delete", "forward", "send"}:
        result["skipped"] = True
    else:
        result["skipped"] = True
    persist_refreshed_tokens(account, provider)
    return result


def decide_and_act(
    db: Session,
    account: EmailAccount,
    email: Email,
    preferences: list[dict] | None = None,
    examples: list[dict] | None = None,
    use_llm: bool | None = None,
) -> AgentDecision:
    unsub = (email.raw_json or {}).get("list_unsubscribe")
    clf = classify_email(
        sender=email.sender,
        subject=email.subject,
        body=email.body_text,
        labels=list(email.labels or []),
        list_unsubscribe=unsub,
        preferences=preferences,
        examples=examples,
        use_llm=use_llm,
    )
    guarded = apply_safety(
        clf,
        email.subject,
        email.body_text,
        extra_floors=extra_floors(db, account.user_id, email.sender, clf.action_type),
        use_llm=use_llm,
    )

    proposed = {
        "action": guarded.action_type,
        "label": clf.label,
        "draft": clf.draft,
        "category": clf.category,
        "used_llm": clf.used_llm,
        "safety_reason": guarded.reason,
    }

    decision = AgentDecision(
        email_id=email.id,
        autonomy_level=guarded.autonomy_level,
        classifier_level=clf.autonomy_level,
        confidence=clf.confidence,
        reasoning=clf.reasoning,
        proposed_action=proposed,
        action_type=guarded.action_type,
        status="pending",
        safety_hit=guarded.safety_hit,
    )
    db.add(decision)
    db.flush()

    if guarded.autonomy_level in {"proceed_silently", "proceed_and_notify"}:
        if guarded.action_type in {"archive", "label"}:
            try:
                result = run_action(account, email, guarded.action_type, clf)
                proposed.update(result)
                decision.proposed_action = proposed
                decision.status = "executed"
                decision.executed_at = datetime.now(timezone.utc)
            except Exception:
                log.exception("action failed on email %s", email.id)
                decision.status = "pending"
                decision.reasoning = (decision.reasoning or "") + " Action failed; left pending."
        else:
            decision.status = "pending"
    elif guarded.autonomy_level == "escalate":
        decision.status = "escalated"
    else:
        if guarded.action_type == "draft_reply" and clf.draft:
            try:
                result = run_action(account, email, "draft_reply", clf)
                proposed.update(result)
                decision.proposed_action = proposed
            except Exception:
                log.exception("draft failed on email %s", email.id)
        decision.status = "pending"

    return decision


def approve_and_run(db: Session, decision: AgentDecision, account: EmailAccount, email: Email) -> AgentDecision:
    clf = Classification(
        autonomy_level=decision.autonomy_level,
        confidence=decision.confidence,
        action_type=decision.action_type,
        reasoning=decision.reasoning,
        draft=(decision.proposed_action or {}).get("draft"),
        label=(decision.proposed_action or {}).get("label"),
        category=(decision.proposed_action or {}).get("category") or "other",
        used_llm=bool((decision.proposed_action or {}).get("used_llm")),
    )
    action = decision.action_type
    if action in {"none", "delete", "forward", "send"}:
        decision.status = "overridden"
        decision.executed_at = datetime.now(timezone.utc)
        return decision
    result = run_action(account, email, action, clf)
    payload = dict(decision.proposed_action or {})
    payload.update(result)
    decision.proposed_action = payload
    decision.status = "executed"
    decision.executed_at = datetime.now(timezone.utc)
    return decision


def retry_pending_autonomous(db: Session, account: EmailAccount) -> int:
    rows = (
        db.query(AgentDecision, Email)
        .join(Email, Email.id == AgentDecision.email_id)
        .filter(
            Email.account_id == account.id,
            AgentDecision.status == "pending",
            AgentDecision.autonomy_level.in_(["proceed_silently", "proceed_and_notify"]),
            AgentDecision.action_type.in_(["archive", "label"]),
        )
        .all()
    )
    n = 0
    for decision, email in rows:
        clf = Classification(
            autonomy_level=decision.autonomy_level,
            confidence=decision.confidence,
            action_type=decision.action_type,
            reasoning=decision.reasoning,
            draft=(decision.proposed_action or {}).get("draft"),
            label=(decision.proposed_action or {}).get("label"),
            category=(decision.proposed_action or {}).get("category") or "other",
            used_llm=bool((decision.proposed_action or {}).get("used_llm")),
        )
        try:
            result = run_action(account, email, decision.action_type, clf)
            payload = dict(decision.proposed_action or {})
            payload.update(result)
            decision.proposed_action = payload
            decision.status = "executed"
            decision.executed_at = datetime.now(timezone.utc)
            n += 1
        except Exception:
            log.exception("retry failed on email %s", email.id)
    return n
