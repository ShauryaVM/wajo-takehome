from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import current_email
from app.config import settings
from app.db import get_db
from app.models import EmailAccount, User


def current_user(email: str = Depends(current_email), db: Session = Depends(get_db)) -> User:
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None:
        user = User(email=settings.demo_user_email)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def active_account_ids(db: Session, user: User) -> list[int]:
    rows = (
        db.query(EmailAccount.id)
        .filter(EmailAccount.user_id == user.id, EmailAccount.is_active.is_(True))
        .all()
    )
    return [row[0] for row in rows]
