from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
import os

from app.config import settings
from app.crypto import encrypt_json
from app.db import get_db
from app.deps import current_user
from app.models import EmailAccount, User
from app.providers.gmail import GMAIL_SCOPES, encrypt_creds
from app.providers.imap_smtp import normalize_secret, test_imap_smtp
from app.schemas import AccountOut, ImapConnectIn

router = APIRouter(prefix="/accounts", tags=["accounts"])


def gmail_redirect_uri() -> str:
    return settings.gmail_callback_url()


def _allow_http_oauth() -> None:
    if settings.api_origin.startswith("http://"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def _deactivate_fixtures(db: Session, user: User) -> None:
    rows = (
        db.query(EmailAccount)
        .filter(
            EmailAccount.user_id == user.id,
            EmailAccount.provider == "fixture",
            EmailAccount.is_active.is_(True),
        )
        .all()
    )
    for row in rows:
        row.is_active = False


def _restore_fixture_if_needed(db: Session, user: User) -> None:
    live = (
        db.query(EmailAccount)
        .filter(
            EmailAccount.user_id == user.id,
            EmailAccount.is_active.is_(True),
            EmailAccount.provider != "fixture",
        )
        .count()
    )
    if live:
        return
    rows = (
        db.query(EmailAccount)
        .filter(EmailAccount.user_id == user.id, EmailAccount.provider == "fixture")
        .all()
    )
    for row in rows:
        row.is_active = True


def _upsert_imap(db: Session, user: User, body: ImapConnectIn) -> EmailAccount:
    password = normalize_secret(body.password)
    addr = body.email_address.strip()
    test_imap_smtp(
        email_address=addr,
        password=password,
        imap_host=body.imap_host.strip(),
        imap_port=body.imap_port,
        smtp_host=body.smtp_host.strip(),
        smtp_port=body.smtp_port,
        username=(body.username or "").strip() or None,
    )
    blob = encrypt_json({"username": (body.username or addr).strip(), "password": password})
    acct = (
        db.query(EmailAccount)
        .filter(
            EmailAccount.user_id == user.id,
            EmailAccount.provider == "imap",
            EmailAccount.email_address == addr,
        )
        .one_or_none()
    )
    if acct is None:
        acct = EmailAccount(
            user_id=user.id,
            provider="imap",
            email_address=addr,
            display_name=body.display_name or addr,
            credentials_encrypted=blob,
            imap_host=body.imap_host.strip(),
            imap_port=body.imap_port,
            smtp_host=body.smtp_host.strip(),
            smtp_port=body.smtp_port,
            is_active=True,
        )
        db.add(acct)
    else:
        acct.display_name = body.display_name or addr
        acct.credentials_encrypted = blob
        acct.imap_host = body.imap_host.strip()
        acct.imap_port = body.imap_port
        acct.smtp_host = body.smtp_host.strip()
        acct.smtp_port = body.smtp_port
        acct.is_active = True
    _deactivate_fixtures(db, user)
    return acct


def _local_user(db: Session, request: Request | None = None) -> User:
    from app.auth import email_from_token

    if request is not None:
        token = request.cookies.get(settings.cookie_name)
        if token:
            try:
                email = email_from_token(token)
                user = db.query(User).filter(User.email == email).one_or_none()
                if user is not None:
                    return user
            except HTTPException:
                pass
    user = db.query(User).filter(User.email == settings.demo_user_email).one_or_none()
    if user is None:
        raise HTTPException(400, "local user is missing; restart the API so seed can run")
    return user


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(EmailAccount).filter(EmailAccount.user_id == user.id).all()
    return rows


@router.post("/imap/test")
def test_imap(body: ImapConnectIn, user: User = Depends(current_user)):
    try:
        return test_imap_smtp(
            email_address=body.email_address.strip(),
            password=body.password,
            imap_host=body.imap_host.strip(),
            imap_port=body.imap_port,
            smtp_host=body.smtp_host.strip(),
            smtp_port=body.smtp_port,
            username=(body.username or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/imap", response_model=AccountOut)
def connect_imap(body: ImapConnectIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        acct = _upsert_imap(db, user, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    db.refresh(acct)
    return acct


@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    acct = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == account_id, EmailAccount.user_id == user.id)
        .one_or_none()
    )
    if acct is None:
        raise HTTPException(404, "account not found")
    if acct.provider == "fixture":
        raise HTTPException(400, "the demo inbox stays")
    acct.is_active = False
    acct.credentials_encrypted = None
    acct.oauth_tokens_encrypted = None
    _restore_fixture_if_needed(db, user)
    db.commit()
    return {"ok": True}


@router.get("/gmail/start")
def gmail_start(_user: User = Depends(current_user)):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            400,
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are empty. App Password IMAP does not need them.",
        )
    from google_auth_oauthlib.flow import Flow

    _allow_http_oauth()
    redirect_uri = gmail_redirect_uri()
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )
    url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    resp = JSONResponse({"url": url, "redirect_uri": redirect_uri})
    resp.set_cookie(
        "steward_oauth_state",
        state,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=600,
        path="/",
    )
    return resp


@router.get("/gmail/callback")
def gmail_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    dest = f"{settings.app_origin.rstrip('/')}/settings"
    if error:
        return RedirectResponse(f"{dest}?error={error}")
    if not code:
        return RedirectResponse(f"{dest}?error=missing_code")
    expected = request.cookies.get("steward_oauth_state")
    if expected and state and expected != state:
        return RedirectResponse(f"{dest}?error=state_mismatch")
    if not settings.google_client_id or not settings.google_client_secret:
        return RedirectResponse(f"{dest}?error=oauth_not_configured")
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build

    _allow_http_oauth()
    redirect_uri = gmail_redirect_uri()
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )
    try:
        flow.fetch_token(code=code)
    except Exception:
        return RedirectResponse(f"{dest}?error=token_exchange_failed")
    creds = flow.credentials
    user = _local_user(db, request)
    try:
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        profile = svc.users().getProfile(userId="me").execute()
    except Exception:
        return RedirectResponse(f"{dest}?error=gmail_profile_failed")
    addr = profile.get("emailAddress") or "gmail"
    blob = encrypt_creds(creds)
    acct = (
        db.query(EmailAccount)
        .filter(
            EmailAccount.user_id == user.id,
            EmailAccount.provider == "gmail",
            EmailAccount.email_address == addr,
        )
        .one_or_none()
    )
    if acct is None:
        acct = EmailAccount(
            user_id=user.id,
            provider="gmail",
            email_address=addr,
            display_name=addr,
            oauth_tokens_encrypted=blob,
            is_active=True,
        )
        db.add(acct)
    else:
        acct.oauth_tokens_encrypted = blob
        acct.is_active = True
        acct.display_name = addr
    _deactivate_fixtures(db, user)
    db.commit()
    resp = RedirectResponse(f"{dest}?connected=gmail")
    resp.delete_cookie("steward_oauth_state", path="/")
    return resp


@router.get("/outlook/start")
def outlook_start(_user: User = Depends(current_user)):
    if not settings.microsoft_client_id or not settings.microsoft_client_secret:
        raise HTTPException(400, "MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET are empty")
    import msal

    app = msal.ConfidentialClientApplication(
        settings.microsoft_client_id,
        authority=f"https://login.microsoftonline.com/{settings.microsoft_tenant}",
        client_credential=settings.microsoft_client_secret,
    )
    url = app.get_authorization_request_url(
        scopes=["Mail.ReadWrite", "Mail.Send", "offline_access", "User.Read"],
        redirect_uri=f"{settings.api_origin.rstrip('/')}/accounts/outlook/callback",
    )
    return {"url": url}


@router.get("/outlook/callback")
def outlook_callback(code: str, request: Request, db: Session = Depends(get_db)):
    import msal
    import httpx

    dest = f"{settings.app_origin.rstrip('/')}/settings"
    app = msal.ConfidentialClientApplication(
        settings.microsoft_client_id,
        authority=f"https://login.microsoftonline.com/{settings.microsoft_tenant}",
        client_credential=settings.microsoft_client_secret,
    )
    result = app.acquire_token_by_authorization_code(
        code,
        scopes=["Mail.ReadWrite", "Mail.Send", "offline_access", "User.Read"],
        redirect_uri=f"{settings.api_origin.rstrip('/')}/accounts/outlook/callback",
    )
    if "access_token" not in result:
        return RedirectResponse(f"{dest}?error=outlook_oauth_failed")
    token_blob = {
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token"),
        "expires_at": None,
    }
    with httpx.Client(timeout=20) as client:
        me = client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {result['access_token']}"},
        )
        me.raise_for_status()
        addr = me.json().get("mail") or me.json().get("userPrincipalName") or "outlook"
    user = _local_user(db, request)
    acct = (
        db.query(EmailAccount)
        .filter(
            EmailAccount.user_id == user.id,
            EmailAccount.provider == "outlook",
            EmailAccount.email_address == addr,
        )
        .one_or_none()
    )
    blob = encrypt_json(token_blob)
    if acct is None:
        acct = EmailAccount(
            user_id=user.id,
            provider="outlook",
            email_address=addr,
            display_name=addr,
            oauth_tokens_encrypted=blob,
            is_active=True,
        )
        db.add(acct)
    else:
        acct.oauth_tokens_encrypted = blob
        acct.is_active = True
    _deactivate_fixtures(db, user)
    db.commit()
    return RedirectResponse(f"{dest}?connected=outlook")
