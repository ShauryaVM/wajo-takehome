from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import current_user
from app.llm_router import llm_configured
from app.models import SafetyRule, User
from app.schemas import SafetyRuleIn, SafetyRuleOut

router = APIRouter(prefix="/settings", tags=["settings"])

SYSTEM_RULES = [
    ("send", "send", "ask_first", "Outbound mail waits for approval"),
    ("delete", "delete", "escalate", "Deletion always escalates"),
    ("forward_external", "forward", "escalate", "Forwarding outside the tenant escalates"),
    ("money", "*", "escalate", "Payment or wire requests escalate"),
    ("prompt_injection", "*", "escalate", "Instruction-override attempts escalate"),
]


def ensure_system_rules(db: Session, user_id: int) -> None:
    existing = {
        r.rule_type
        for r in db.query(SafetyRule).filter(SafetyRule.user_id == user_id, SafetyRule.is_system.is_(True)).all()
    }
    for rule_type, action_type, floor, label in SYSTEM_RULES:
        if rule_type in existing:
            continue
        db.add(
            SafetyRule(
                user_id=user_id,
                rule_type=rule_type,
                action_type=action_type,
                min_autonomy_level=floor,
                is_system=True,
                label=label,
            )
        )


@router.get("")
def get_settings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    ensure_system_rules(db, user.id)
    db.commit()
    rules = db.query(SafetyRule).filter(SafetyRule.user_id == user.id).order_by(SafetyRule.id).all()
    return {
        "llm": {
            "provider": settings.llm_provider,
            "openai_configured": bool(settings.openai_api_key),
            "anthropic_configured": bool(settings.anthropic_api_key),
            "ready": llm_configured(),
            "openai_model": settings.openai_model,
            "anthropic_model": settings.anthropic_model,
        },
        "safety_rules": [SafetyRuleOut.model_validate(r).model_dump() for r in rules],
        "user": {"email": user.email},
        "google_oauth_configured": bool(settings.google_client_id and settings.google_client_secret),
        "microsoft_oauth_configured": bool(
            settings.microsoft_client_id and settings.microsoft_client_secret
        ),
        "gmail_redirect_uri": settings.gmail_callback_url(),
    }


@router.post("/safety", response_model=SafetyRuleOut)
def add_rule(body: SafetyRuleIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.min_autonomy_level not in {
        "proceed_silently",
        "proceed_and_notify",
        "ask_first",
        "escalate",
    }:
        raise HTTPException(400, "bad min_autonomy_level")
    row = SafetyRule(
        user_id=user.id,
        rule_type=body.rule_type,
        action_type=body.action_type,
        min_autonomy_level=body.min_autonomy_level,
        is_system=False,
        label=body.label or body.rule_type,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/safety/{rule_id}", response_model=SafetyRuleOut)
def patch_rule(
    rule_id: int,
    body: SafetyRuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    row = (
        db.query(SafetyRule)
        .filter(SafetyRule.id == rule_id, SafetyRule.user_id == user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "rule not found")
    if row.is_system:
        raise HTTPException(400, "system floors cannot be edited")
    row.rule_type = body.rule_type
    row.action_type = body.action_type
    row.min_autonomy_level = body.min_autonomy_level
    row.label = body.label or row.label
    db.commit()
    db.refresh(row)
    return row


@router.delete("/safety/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = (
        db.query(SafetyRule)
        .filter(SafetyRule.id == rule_id, SafetyRule.user_id == user.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "rule not found")
    if row.is_system:
        raise HTTPException(400, "system floors cannot be removed")
    db.delete(row)
    db.commit()
    return {"ok": True}
