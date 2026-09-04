import secrets

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.auth import current_email, make_session
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str
    password: str


class MeOut(BaseModel):
    email: str


@router.post("/login")
def login(body: LoginBody, response: Response):
    email_ok = secrets.compare_digest(str(body.email).strip().lower(), settings.demo_user_email.lower())
    pass_ok = secrets.compare_digest(body.password, settings.demo_user_password)
    if not (email_ok and pass_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad email or password")

    token = make_session(settings.demo_user_email)
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return {"email": settings.demo_user_email}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(settings.cookie_name, path="/")
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(email: str = Depends(current_email)):
    return MeOut(email=email)
