"""initial tables for mail, decisions, feedback

Revision ID: 001_initial
Revises:
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "email_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("email_address", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("oauth_tokens_encrypted", sa.Text(), nullable=True),
        sa.Column("smtp_host", sa.String(length=255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("imap_host", sa.String(length=255), nullable=True),
        sa.Column("imap_port", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_email_accounts_user_id", "email_accounts", ["user_id"])

    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("email_accounts.id"), nullable=False),
        sa.Column("provider_message_id", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=998), nullable=False, server_default=""),
        sa.Column("sender", sa.String(length=512), nullable=False),
        sa.Column("to_addresses", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("body_preview", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("labels", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "provider_message_id", name="uq_email_provider_msg"),
    )
    op.create_index("ix_emails_user_id", "emails", ["user_id"])
    op.create_index("ix_emails_account_id", "emails", ["account_id"])
    op.create_index("ix_emails_received_at", "emails", ["received_at"])

    op.create_table(
        "agent_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email_id", sa.Integer(), sa.ForeignKey("emails.id"), nullable=False),
        sa.Column("autonomy_level", sa.String(length=32), nullable=False),
        sa.Column("classifier_level", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column("proposed_action", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("action_type", sa.String(length=64), nullable=False, server_default="none"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("safety_hit", sa.String(length=64), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_decisions_email_id", "agent_decisions", ["email_id"])
    op.create_index("ix_agent_decisions_autonomy_level", "agent_decisions", ["autonomy_level"])
    op.create_index("ix_agent_decisions_status", "agent_decisions", ["status"])
    op.create_index("ix_agent_decisions_created_at", "agent_decisions", ["created_at"])

    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("agent_decisions.id"), nullable=False),
        sa.Column("feedback_type", sa.String(length=32), nullable=False),
        sa.Column("corrected_autonomy_level", sa.String(length=32), nullable=True),
        sa.Column("user_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feedback_decision_id", "feedback", ["decision_id"])

    op.create_table(
        "preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("pattern_type", sa.String(length=32), nullable=False),
        sa.Column("pattern_value", sa.String(length=255), nullable=False),
        sa.Column("preferred_autonomy", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.3"),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "pattern_type", "pattern_value", name="uq_pref_pattern"),
    )
    op.create_index("ix_preferences_user_id", "preferences", ["user_id"])

    op.create_table(
        "safety_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rule_type", sa.String(length=64), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("min_autonomy_level", sa.String(length=32), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("label", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_safety_rules_user_id", "safety_rules", ["user_id"])


def downgrade() -> None:
    op.drop_table("safety_rules")
    op.drop_table("preferences")
    op.drop_table("feedback")
    op.drop_table("agent_decisions")
    op.drop_table("emails")
    op.drop_table("email_accounts")
    op.drop_table("users")
