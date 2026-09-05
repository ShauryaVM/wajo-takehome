from app.action_engine import decide_and_act
from app.classifier import guess_category
from app.learning import preferences_for, similar_decisions
from app.models import Email, EmailAccount


def after_new_mail(db, account: EmailAccount, email: Email, _msg=None) -> None:
    category = guess_category(
        email.sender, email.subject, email.body_text, list(email.labels or [])
    )
    prefs = preferences_for(db, account.user_id, email.sender, category)
    examples = similar_decisions(db, account.user_id, email.sender, category)
    decide_and_act(db, account, email, preferences=prefs, examples=examples)
