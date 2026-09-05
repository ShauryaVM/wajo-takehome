from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DecisionOut(BaseModel):
    id: int
    email_id: int
    autonomy_level: str
    classifier_level: str
    confidence: float
    reasoning: str
    proposed_action: dict[str, Any]
    action_type: str
    status: str
    safety_hit: str | None
    executed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackIn(BaseModel):
    feedback_type: str
    corrected_autonomy_level: str | None = None
    user_comment: str | None = None


class FeedbackOut(BaseModel):
    id: int
    decision_id: int
    feedback_type: str
    corrected_autonomy_level: str | None
    user_comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EmailListItem(BaseModel):
    id: int
    subject: str
    sender: str
    preview: str
    received_at: datetime
    labels: list[Any]
    decision: DecisionOut | None = None


class EmailDetail(EmailListItem):
    body_text: str
    to_addresses: list[Any]
    account_id: int
    provider_message_id: str
    feedback: list[FeedbackOut] = []


class AccountOut(BaseModel):
    id: int
    provider: str
    email_address: str
    display_name: str
    is_active: bool
    last_sync_at: datetime | None
    imap_host: str | None
    smtp_host: str | None

    model_config = {"from_attributes": True}


class ImapConnectIn(BaseModel):
    email_address: str
    username: str | None = None
    password: str
    imap_host: str
    imap_port: int = 993
    smtp_host: str
    smtp_port: int = 587
    display_name: str = ""


class SafetyRuleOut(BaseModel):
    id: int
    rule_type: str
    action_type: str
    min_autonomy_level: str
    is_system: bool
    label: str

    model_config = {"from_attributes": True}


class SafetyRuleIn(BaseModel):
    rule_type: str
    action_type: str = "*"
    min_autonomy_level: str
    label: str = ""
