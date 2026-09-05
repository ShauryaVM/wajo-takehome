from app.models import EmailAccount
from app.providers.base import EmailProvider
from app.providers.fixture import FixtureProvider


def provider_for(account: EmailAccount) -> EmailProvider:
    if account.provider == "fixture":
        return FixtureProvider(account_email=account.email_address)
    raise ValueError(f"unknown provider {account.provider}")
