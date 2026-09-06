from datetime import datetime, timezone
import logging

from sqlalchemy.orm import Session

from app.action_engine import retry_pending_autonomous
from app.models import Email, EmailAccount
from app.providers.router import persist_refreshed_tokens, provider_for

log = logging.getLogger("steward.sync")


def upsert_message(db: Session, account: EmailAccount, msg) -> Email | None:
    existing = (
        db.query(Email)
        .filter(
            Email.account_id == account.id,
            Email.provider_message_id == msg.provider_message_id,
        )
        .one_or_none()
    )
    if existing:
        return None
    row = Email(
        user_id=account.user_id,
        account_id=account.id,
        provider_message_id=msg.provider_message_id,
        subject=msg.subject or "",
        sender=msg.sender,
        to_addresses=msg.to_addresses,
        body_preview=(msg.body_preview or "")[:500],
        body_text=msg.body_text or "",
        labels=msg.labels or [],
        received_at=msg.received_at,
        raw_json={
            **(msg.raw or {}),
            "list_unsubscribe": msg.list_unsubscribe,
        },
    )
    db.add(row)
    db.flush()
    return row


def sync_account(db: Session, account: EmailAccount, on_new=None) -> int:
    provider = provider_for(account)
    known = {
        mid
        for (mid,) in db.query(Email.provider_message_id).filter(Email.account_id == account.id).all()
    }
    first = account.last_sync_at is None
    messages = provider.list_messages(
        since=account.last_sync_at,
        limit=100 if first else 50,
        skip_ids=known,
    )
    created = 0
    for msg in messages:
        row = upsert_message(db, account, msg)
        if row is None:
            continue
        created += 1
        if on_new:
            try:
                on_new(db, account, row, msg)
            except Exception:
                log.exception("classify failed for email %s", row.id)
    persist_refreshed_tokens(account, provider)
    account.last_sync_at = datetime.now(timezone.utc)
    try:
        retry_pending_autonomous(db, account)
    except Exception:
        log.exception("retry pending actions failed for account %s", account.id)
    return created


def sync_all(db: Session, on_new=None) -> int:
    accounts = db.query(EmailAccount).filter(EmailAccount.is_active.is_(True)).all()
    total = 0
    for account in accounts:
        try:
            total += sync_account(db, account, on_new=on_new)
        except Exception:
            log.exception("sync failed for account %s (%s)", account.id, account.provider)
    return total
