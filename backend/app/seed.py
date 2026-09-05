from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from sqlalchemy.orm import Session

from app.action_engine import decide_and_act
from app.config import settings
from app.learning import record_feedback
from app.models import AgentDecision, Email, EmailAccount, Preference, User
from app.routers.settings import ensure_system_rules

HISTORY_START = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)


def _user(db: Session) -> User:
    user = db.query(User).filter(User.email == settings.demo_user_email).one_or_none()
    if user is None:
        user = User(email=settings.demo_user_email)
        db.add(user)
        db.flush()
    return user


def _fixture_account(db: Session, user: User) -> EmailAccount:
    acct = (
        db.query(EmailAccount)
        .filter(EmailAccount.user_id == user.id, EmailAccount.provider == "fixture")
        .one_or_none()
    )
    if acct is None:
        acct = EmailAccount(
            user_id=user.id,
            provider="fixture",
            email_address=settings.demo_user_email,
            display_name="Demo inbox",
        )
        db.add(acct)
        db.flush()
    return acct


def _add_email(
    db: Session,
    user: User,
    acct: EmailAccount,
    *,
    mid: str,
    sender: str,
    subject: str,
    body: str,
    received_at: datetime,
    labels: list[str] | None = None,
) -> Email | None:
    exists = (
        db.query(Email)
        .filter(Email.account_id == acct.id, Email.provider_message_id == mid)
        .one_or_none()
    )
    if exists:
        return None
    row = Email(
        user_id=user.id,
        account_id=acct.id,
        provider_message_id=mid,
        subject=subject,
        sender=sender,
        to_addresses=[settings.demo_user_email],
        body_preview=body[:180],
        body_text=body,
        labels=labels or ["INBOX"],
        received_at=received_at,
        raw_json={},
    )
    db.add(row)
    db.flush()
    return row


def _stamp_decision(
    db: Session,
    email: Email,
    *,
    level: str,
    action: str,
    status: str,
    reasoning: str,
    confidence: float,
    when: datetime,
    safety_hit: str | None = None,
    draft: str | None = None,
    category: str = "other",
) -> AgentDecision:
    d = AgentDecision(
        email_id=email.id,
        autonomy_level=level,
        classifier_level=level,
        confidence=confidence,
        reasoning=reasoning,
        proposed_action={"action": action, "category": category, "draft": draft, "used_llm": False},
        action_type=action,
        status=status,
        safety_hit=safety_hit,
        created_at=when,
        executed_at=when if status == "executed" else None,
    )
    db.add(d)
    db.flush()
    return d


def _history(db: Session, user: User, acct: EmailAccount) -> None:
    # Early days: agent asks about newsletters. User keeps saying too cautious.
    brews = [
        "☕ Payroll software, a delayed IPO, and one messy all-hands",
        "☕ Robotaxis, a cooler CPI print, and someone's Slack leak",
        "☕ Cheap flights, a quiet layoff memo, and ad tech leftovers",
        "☕ A new chip rumor and the same three fintech headlines",
    ]
    for i, subj in enumerate(brews):
        when = HISTORY_START + timedelta(days=i, hours=2)
        email = _add_email(
            db,
            user,
            acct,
            mid=f"hist-brew-{i}",
            sender="Morning Brew <crew@morningbrew.com>",
            subject=subj,
            body="Good morning.\n\nThe usual mix of markets and tech gossip. Unsubscribe if you hate us.\n",
            received_at=when,
            labels=["INBOX", "CATEGORY_PROMOTIONS"],
        )
        if not email:
            continue
        # first two: asked, then user said too cautious. later: silent.
        if i < 2:
            d = _stamp_decision(
                db,
                email,
                level="ask_first",
                action="archive",
                status="executed",
                reasoning="First time seeing this sender. I asked before archiving.",
                confidence=0.42,
                when=when + timedelta(minutes=4),
                category="newsletter",
            )
            record_feedback(db, d, "too_cautious")
        else:
            _stamp_decision(
                db,
                email,
                level="proceed_silently",
                action="archive",
                status="executed",
                reasoning="You've marked this sender too cautious twice. Archiving without a ping.",
                confidence=0.81,
                when=when + timedelta(minutes=3),
                category="newsletter",
            )

    receipts = [
        ("Stripe <receipts@stripe.com>", "Your receipt from Northwind Inc. #2081", "Northwind Inc. paid $42.00 to Notion.\nThis is not a bill.\n", "receipt"),
        ("Amazon <shipment-tracking@amazon.com>", "Delivered: USB-C cable", "Delivered today at 2:14pm. Left at the door.\n", "receipt"),
        ("Uber Receipts <uber.receipts@uber.com>", "Your Friday morning trip", "Trip total $18.40. Thanks for riding.\n", "receipt"),
        ("GitHub <notifications@github.com>", "[northwind/api] deploy-staging succeeded", "Workflow deploy-staging completed successfully on main.\n", "github"),
    ]
    for i, (sender, subj, body, cat) in enumerate(receipts):
        when = HISTORY_START + timedelta(days=3 + i, hours=8)
        email = _add_email(db, user, acct, mid=f"hist-txn-{i}", sender=sender, subject=subj, body=body, received_at=when)
        if not email:
            continue
        _stamp_decision(
            db,
            email,
            level="proceed_and_notify",
            action="label",
            status="executed",
            reasoning=f"Transactional {cat}. Labeled and dropped a note in the feed.",
            confidence=0.77,
            when=when + timedelta(minutes=2),
            category=cat,
        )

    work = [
        (
            "Priya Shah <priya@northwind.co>",
            "security questionnaire this month?",
            "Klaus asked if we can do a SIG Lite in September. I said maybe. Want me to stall?\n",
            "ask_first",
            "draft_reply",
            "pending",
            "Work question that wants a reply. Drafted and waiting.",
        ),
        (
            "Sam Ortiz <sam.ortiz@northwind.co>",
            "staging migrate still failing",
            "Same relation error. I didn't touch prod. Can you look after lunch?\n",
            "ask_first",
            "draft_reply",
            "executed",
            "Asked before drafting. You approved the reply.",
        ),
        (
            "Jordan Hale <jordan@northwind.co>",
            "PTO next Thursday",
            "Taking Thursday. Lattice call would need coverage if it slips to that week.\n",
            "ask_first",
            "draft_reply",
            "dismissed",
            "Personal-ish work mail. You dismissed the draft.",
        ),
    ]
    for i, (sender, subj, body, level, action, status, why) in enumerate(work):
        when = HISTORY_START + timedelta(days=7 + i, hours=11)
        email = _add_email(db, user, acct, mid=f"hist-work-{i}", sender=sender, subject=subj, body=body, received_at=when)
        if not email:
            continue
        d = _stamp_decision(
            db,
            email,
            level=level,
            action=action,
            status=status,
            reasoning=why,
            confidence=0.64,
            when=when + timedelta(minutes=6),
            category="work",
            draft="Happy to look. I'll reply in-thread." if action == "draft_reply" else None,
        )
        if status == "executed" and i == 1:
            record_feedback(db, d, "good")

    when = HISTORY_START + timedelta(days=10, hours=16)
    email = _add_email(
        db,
        user,
        acct,
        mid="hist-press",
        sender="Lila Grant <lila.grant@techcrunch.com>",
        subject="quick fact check on Lattice",
        body="Hi, I'm at TechCrunch. Can I confirm Northwind is the SSO vendor? Need a line today.\n",
        received_at=when,
    )
    if email:
        _stamp_decision(
            db,
            email,
            level="escalate",
            action="none",
            status="escalated",
            reasoning="Press. I'm not touching this.",
            confidence=0.9,
            when=when + timedelta(minutes=1),
            category="other",
        )

    when = HISTORY_START + timedelta(days=6, hours=4)
    email = _add_email(
        db,
        user,
        acct,
        mid="hist-verge",
        sender="The Verge <noreply@mail.theverge.com>",
        subject="The Verge: leftover Vision SKU",
        body="Today in The Verge. Unsubscribe at the bottom.\n",
        received_at=when,
        labels=["INBOX", "CATEGORY_PROMOTIONS"],
    )
    if email:
        d = _stamp_decision(
            db,
            email,
            level="ask_first",
            action="archive",
            status="executed",
            reasoning="Newsletter, but I hadn't seen this domain enough times yet.",
            confidence=0.5,
            when=when + timedelta(minutes=5),
            category="newsletter",
        )
        record_feedback(db, d, "too_cautious")


def _fixture_inbox(db: Session, user: User, acct: EmailAccount) -> None:
    path = Path(__file__).resolve().parent / "providers" / "fixtures" / "inbox.json"
    rows = json.loads(path.read_text())
    for row in rows:
        received = datetime.fromisoformat(row["received_at"])
        _add_email(
            db,
            user,
            acct,
            mid=row["id"],
            sender=row["sender"],
            subject=row.get("subject", ""),
            body=row["body"],
            received_at=received,
            labels=row.get("labels") or ["INBOX"],
        )
        email = (
            db.query(Email)
            .filter(Email.account_id == acct.id, Email.provider_message_id == row["id"])
            .one()
        )
        email.raw_json = {**row, "list_unsubscribe": row.get("list_unsubscribe")}
        has = db.query(AgentDecision).filter(AgentDecision.email_id == email.id).first()
        if has:
            continue
        decide_and_act(db, acct, email)


def _prefs(db: Session, user: User) -> None:
    wanted = [
        ("sender_domain", "morningbrew.com", "proceed_silently", 0.84, 4),
        ("category", "newsletter", "proceed_silently", 0.76, 6),
        ("sender_domain", "stripe.com", "proceed_and_notify", 0.7, 3),
        ("category", "receipt", "proceed_and_notify", 0.72, 4),
        ("sender_domain", "northwind.co", "ask_first", 0.62, 5),
    ]
    for ptype, value, level, conf, n in wanted:
        exists = (
            db.query(Preference)
            .filter(
                Preference.user_id == user.id,
                Preference.pattern_type == ptype,
                Preference.pattern_value == value,
            )
            .one_or_none()
        )
        if exists:
            exists.preferred_autonomy = level
            exists.confidence = conf
            exists.sample_count = n
            continue
        db.add(
            Preference(
                user_id=user.id,
                pattern_type=ptype,
                pattern_value=value,
                preferred_autonomy=level,
                confidence=conf,
                sample_count=n,
            )
        )


def seed_if_empty(db: Session) -> None:
    user = _user(db)
    acct = _fixture_account(db, user)
    ensure_system_rules(db, user.id)
    _history(db, user, acct)
    _fixture_inbox(db, user, acct)
    _prefs(db, user)
