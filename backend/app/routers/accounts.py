from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.crypto import encrypt_json
from app.db import get_db
from app.deps import current_user
from app.models import EmailAccount, User
from app.providers.gmail import GMAIL_SCOPES, encrypt_creds
from app.schemas import AccountOut, ImapConnectIn

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(EmailAccount).filter(EmailAccount.user_id == user.id).all()
    return rows


@router.post("/imap", response_model=AccountOut)
def connect_imap(body: ImapConnectIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    blob = encrypt_json({"username": body.username or body.email_address, "password": body.password})
    acct = EmailAccount(
        user_id=user.id,
        provider="imap",
        email_address=body.email_address,
        display_name=body.display_name or body.email_address,
        credentials_encrypted=blob,
        imap_host=body.imap_host,
        imap_port=body.imap_port,
        smtp_host=body.smtp_host,
        smtp_port=body.smtp_port,
    )
    db.add(acct)
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
    db.commit()
    return {"ok": True}


@router.get("/gmail/start")
def gmail_start():
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(400, "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are empty")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [f"{settings.api_origin}/accounts/gmail/callback"],
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=f"{settings.api_origin}/accounts/gmail/callback",
    )
    url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return {"url": url}


@router.get("/gmail/callback")
def gmail_callback(code: str, db: Session = Depends(get_db)):
    if not settings.google_client_id:
        raise HTTPException(400, "gmail oauth is not configured")
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [f"{settings.api_origin}/accounts/gmail/callback"],
            }
        },
        scopes=GMAIL_SCOPES,
        redirect_uri=f"{settings.api_origin}/accounts/gmail/callback",
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    user = db.query(User).filter(User.email == settings.demo_user_email).one()
    from googleapiclient.discovery import build

    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = svc.users().getProfile(userId="me").execute()
    addr = profile.get("emailAddress") or "gmail"
    acct = EmailAccount(
        user_id=user.id,
        provider="gmail",
        email_address=addr,
        display_name=addr,
        oauth_tokens_encrypted=encrypt_creds(creds),
    )
    db.add(acct)
    db.commit()
    return RedirectResponse(f"{settings.app_origin}/settings?connected=gmail")


@router.get("/outlook/start")
def outlook_start():
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
        redirect_uri=f"{settings.api_origin}/accounts/outlook/callback",
    )
    return {"url": url}


@router.get("/outlook/callback")
def outlook_callback(code: str, db: Session = Depends(get_db)):
    import msal
    import httpx

    app = msal.ConfidentialClientApplication(
        settings.microsoft_client_id,
        authority=f"https://login.microsoftonline.com/{settings.microsoft_tenant}",
        client_credential=settings.microsoft_client_secret,
    )
    result = app.acquire_token_by_authorization_code(
        code,
        scopes=["Mail.ReadWrite", "Mail.Send", "offline_access", "User.Read"],
        redirect_uri=f"{settings.api_origin}/accounts/outlook/callback",
    )
    if "access_token" not in result:
        raise HTTPException(400, result.get("error_description") or "outlook oauth failed")
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
    user = db.query(User).filter(User.email == settings.demo_user_email).one()
    acct = EmailAccount(
        user_id=user.id,
        provider="outlook",
        email_address=addr,
        display_name=addr,
        oauth_tokens_encrypted=encrypt_json(token_blob),
    )
    db.add(acct)
    db.commit()
    return RedirectResponse(f"{settings.app_origin}/settings?connected=outlook")
