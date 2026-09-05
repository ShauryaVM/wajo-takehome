from app.models import EmailAccount
from app.providers.base import EmailProvider
from app.providers.fixture import FixtureProvider
from app.providers.gmail import GmailProvider
from app.providers.imap_smtp import ImapSmtpProvider
from app.providers.outlook import OutlookProvider


def persist_refreshed_tokens(account: EmailAccount, provider) -> None:
    fn = getattr(provider, "refreshed_blob", None)
    if not callable(fn):
        return
    blob = fn()
    if blob and blob != account.oauth_tokens_encrypted:
        account.oauth_tokens_encrypted = blob


def provider_for(account: EmailAccount) -> EmailProvider:
    if account.provider == "fixture":
        return FixtureProvider(account_email=account.email_address)
    if account.provider == "gmail":
        if not account.oauth_tokens_encrypted:
            raise ValueError("gmail account is missing oauth tokens")
        return GmailProvider(account.oauth_tokens_encrypted)
    if account.provider == "outlook":
        if not account.oauth_tokens_encrypted:
            raise ValueError("outlook account is missing oauth tokens")
        return OutlookProvider(account.oauth_tokens_encrypted)
    if account.provider == "imap":
        if not account.credentials_encrypted:
            raise ValueError("imap account is missing credentials")
        return ImapSmtpProvider(
            credentials_encrypted=account.credentials_encrypted,
            imap_host=account.imap_host or "",
            imap_port=account.imap_port,
            smtp_host=account.smtp_host,
            smtp_port=account.smtp_port,
            email_address=account.email_address,
        )
    raise ValueError(f"unknown provider {account.provider}")
