from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.action_engine import approve_and_run
from app.db import get_db
from app.deps import active_account_ids, current_user
from app.learning import record_feedback
from app.models import AgentDecision, Email, EmailAccount, Feedback, User
from app.pipeline import after_new_mail
from app.schemas import DecisionOut, EmailDetail, EmailListItem, FeedbackIn, FeedbackOut
from app.sync import sync_all

router = APIRouter(tags=["mail"])


def _latest_map(db: Session, email_ids: list[int]) -> dict[int, AgentDecision]:
    if not email_ids:
        return {}
    sub = (
        db.query(AgentDecision.email_id, func.max(AgentDecision.id).label("mid"))
        .filter(AgentDecision.email_id.in_(email_ids))
        .group_by(AgentDecision.email_id)
        .subquery()
    )
    rows = (
        db.query(AgentDecision)
        .join(sub, AgentDecision.id == sub.c.mid)
        .all()
    )
    return {d.email_id: d for d in rows}


def _item(email: Email, decision: AgentDecision | None) -> EmailListItem:
    return EmailListItem(
        id=email.id,
        subject=email.subject,
        sender=email.sender,
        preview=email.body_preview,
        received_at=email.received_at,
        labels=list(email.labels or []),
        decision=DecisionOut.model_validate(decision) if decision else None,
    )


def _quiet_archive(decision: AgentDecision | None) -> bool:
    if decision is None:
        return False
    return (
        decision.autonomy_level == "proceed_silently"
        and decision.status == "executed"
        and decision.action_type == "archive"
    )


@router.get("/emails", response_model=list[EmailListItem])
def list_emails(
    q: str = "",
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    query = db.query(Email).filter(Email.user_id == user.id)
    ids = active_account_ids(db, user)
    if not ids:
        return []
    query = query.filter(Email.account_id.in_(ids))
    if q:
        like = f"%{q}%"
        query = query.filter((Email.subject.ilike(like)) | (Email.sender.ilike(like)))
    rows = query.order_by(Email.received_at.desc()).limit(200).all()
    latest = _latest_map(db, [e.id for e in rows])
    items = []
    for e in rows:
        d = latest.get(e.id)
        if status and (d is None or d.status != status):
            continue
        if _quiet_archive(d):
            continue
        items.append(_item(e, d))
    return items


@router.get("/emails/{email_id}", response_model=EmailDetail)
def get_email(email_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    email = db.query(Email).filter(Email.id == email_id, Email.user_id == user.id).one_or_none()
    if email is None:
        raise HTTPException(404, "email not found")
    if email.account_id not in active_account_ids(db, user):
        raise HTTPException(404, "email not found")
    latest = _latest_map(db, [email.id]).get(email.id)
    base = _item(email, latest)
    return EmailDetail(
        **base.model_dump(),
        body_text=email.body_text,
        to_addresses=list(email.to_addresses or []),
        account_id=email.account_id,
        provider_message_id=email.provider_message_id,
    )


@router.get("/feed", response_model=list[dict])
def feed(db: Session = Depends(get_db), user: User = Depends(current_user), limit: int = Query(80, le=200)):
    ids = active_account_ids(db, user)
    if not ids:
        return []
    rows = (
        db.query(AgentDecision, Email)
        .join(Email, Email.id == AgentDecision.email_id)
        .filter(
            Email.user_id == user.id,
            Email.account_id.in_(ids),
            AgentDecision.autonomy_level != "proceed_silently",
        )
        .order_by(AgentDecision.created_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for d, e in rows:
        fbs = db.query(Feedback).filter(Feedback.decision_id == d.id).all()
        out.append(
            {
                "decision": DecisionOut.model_validate(d).model_dump(mode="json"),
                "email": {
                    "id": e.id,
                    "subject": e.subject,
                    "sender": e.sender,
                    "preview": e.body_preview,
                    "received_at": e.received_at.isoformat(),
                },
                "feedback": [FeedbackOut.model_validate(f).model_dump(mode="json") for f in fbs],
            }
        )
    return out


@router.get("/approvals", response_model=list[dict])
def approvals(db: Session = Depends(get_db), user: User = Depends(current_user)):
    ids = active_account_ids(db, user)
    if not ids:
        return []
    rows = (
        db.query(AgentDecision, Email)
        .join(Email, Email.id == AgentDecision.email_id)
        .filter(
            Email.user_id == user.id,
            Email.account_id.in_(ids),
            AgentDecision.status.in_(["pending", "escalated"]),
        )
        .order_by(AgentDecision.created_at.desc())
        .all()
    )
    return [
        {
            "decision": DecisionOut.model_validate(d).model_dump(mode="json"),
            "email": {
                "id": e.id,
                "subject": e.subject,
                "sender": e.sender,
                "preview": e.body_preview,
                "body_text": e.body_text,
                "received_at": e.received_at.isoformat(),
            },
        }
        for d, e in rows
    ]


@router.post("/decisions/{decision_id}/approve")
def approve(decision_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    decision, email, account = _owned_decision(db, user, decision_id)
    approve_and_run(db, decision, account, email)
    db.commit()
    db.refresh(decision)
    return DecisionOut.model_validate(decision)


@router.post("/decisions/{decision_id}/dismiss")
def dismiss(decision_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    decision, _email, _account = _owned_decision(db, user, decision_id)
    decision.status = "dismissed"
    db.commit()
    return DecisionOut.model_validate(decision)


@router.post("/decisions/{decision_id}/feedback", response_model=FeedbackOut)
def feedback(
    decision_id: int,
    body: FeedbackIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    decision, _email, _account = _owned_decision(db, user, decision_id)
    if body.feedback_type not in {"good", "too_aggressive", "too_cautious", "wrong_action"}:
        raise HTTPException(400, "unknown feedback_type")
    fb = record_feedback(
        db,
        decision,
        body.feedback_type,
        corrected_autonomy_level=body.corrected_autonomy_level,
        user_comment=body.user_comment,
    )
    db.commit()
    db.refresh(fb)
    return fb


@router.post("/sync")
def trigger_sync(db: Session = Depends(get_db), user: User = Depends(current_user)):
    n = sync_all(db, on_new=after_new_mail)
    db.commit()
    return {"new_messages": n}


def _owned_decision(db: Session, user: User, decision_id: int):
    decision = db.query(AgentDecision).filter(AgentDecision.id == decision_id).one_or_none()
    if decision is None:
        raise HTTPException(404, "decision not found")
    email = db.query(Email).filter(Email.id == decision.email_id, Email.user_id == user.id).one_or_none()
    if email is None:
        raise HTTPException(404, "decision not found")
    account = db.query(EmailAccount).filter(EmailAccount.id == email.account_id).one()
    return decision, email, account
