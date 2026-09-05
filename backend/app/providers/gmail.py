from datetime import datetime, timezone
import base64
import email as emaillib
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
import re

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import settings
from app.crypto import decrypt_json, encrypt_json
from app.providers.base import FetchedMessage, SendPayload

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]


def creds_from_encrypted(blob: str) -> Credentials:
    data = decrypt_json(blob)
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=data.get("client_id") or settings.google_client_id,
        client_secret=data.get("client_secret") or settings.google_client_secret,
        scopes=data.get("scopes") or GMAIL_SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def encrypt_creds(creds: Credentials) -> str:
    return encrypt_json(
        {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or GMAIL_SCOPES),
        }
    )


def _walk_parts(payload: dict) -> tuple[str, str | None]:
    mime = payload.get("mimeType") or ""
    body = payload.get("body") or {}
    data = body.get("data")
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers") or []}
    unsub = headers.get("list-unsubscribe")
    text = ""
    if data and mime.startswith("text/plain"):
        text = base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")
    elif data and mime.startswith("text/html") and not text:
        html = base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")
        text = re.sub(r"<[^>]+>", " ", html)
    for part in payload.get("parts") or []:
        nested, nested_unsub = _walk_parts(part)
        if nested and not text:
            text = nested
        if nested_unsub and not unsub:
            unsub = nested_unsub
    return text, unsub


def _header_map(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers") or []}


class GmailProvider:
    def __init__(self, tokens_encrypted: str):
        self._blob = tokens_encrypted
        self.creds = creds_from_encrypted(tokens_encrypted)
        self.service = build("gmail", "v1", credentials=self.creds, cache_discovery=False)

    def refreshed_blob(self) -> str:
        return encrypt_creds(self.creds)

    def list_messages(self, since: datetime | None = None, limit: int = 50) -> list[FetchedMessage]:
        q_parts = []
        if since:
            q_parts.append(f"after:{int(since.timestamp())}")
        kwargs = {"userId": "me", "maxResults": min(limit, 100)}
        if q_parts:
            kwargs["q"] = " ".join(q_parts)
        resp = self.service.users().messages().list(**kwargs).execute()
        out: list[FetchedMessage] = []
        for stub in resp.get("messages") or []:
            full = (
                self.service.users()
                .messages()
                .get(userId="me", id=stub["id"], format="full")
                .execute()
            )
            payload = full.get("payload") or {}
            headers = _header_map(payload)
            body, unsub = _walk_parts(payload)
            if not unsub:
                unsub = headers.get("list-unsubscribe")
            internal = full.get("internalDate")
            if internal:
                received = datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc)
            else:
                received = parsedate_to_datetime(headers.get("date", ""))
                if received.tzinfo is None:
                    received = received.replace(tzinfo=timezone.utc)
            preview = (full.get("snippet") or body[:180]).strip()
            out.append(
                FetchedMessage(
                    provider_message_id=full["id"],
                    subject=headers.get("subject", ""),
                    sender=headers.get("from", ""),
                    to_addresses=[a.strip() for a in headers.get("to", "").split(",") if a.strip()],
                    body_text=body.strip(),
                    body_preview=preview[:500],
                    labels=full.get("labelIds") or [],
                    received_at=received,
                    raw={"id": full["id"], "threadId": full.get("threadId"), "headers": headers},
                    list_unsubscribe=unsub,
                )
            )
        return out

    def archive(self, message_id: str) -> None:
        self.service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["INBOX"]},
        ).execute()

    def apply_label(self, message_id: str, label: str) -> None:
        label_id = self._ensure_label(label)
        self.service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()

    def _ensure_label(self, name: str) -> str:
        existing = self.service.users().labels().list(userId="me").execute().get("labels") or []
        for lab in existing:
            if lab.get("name", "").lower() == name.lower():
                return lab["id"]
        created = (
            self.service.users()
            .labels()
            .create(
                userId="me",
                body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
            )
            .execute()
        )
        return created["id"]

    def _raw_mime(self, payload: SendPayload) -> str:
        msg = MIMEText(payload.body, "plain", "utf-8")
        msg["To"] = ", ".join(payload.to)
        msg["Subject"] = payload.subject
        if payload.cc:
            msg["Cc"] = ", ".join(payload.cc)
        if payload.in_reply_to:
            msg["In-Reply-To"] = payload.in_reply_to
            msg["References"] = payload.in_reply_to
        return base64.urlsafe_b64encode(msg.as_bytes()).decode()

    def create_draft(self, payload: SendPayload) -> str:
        created = (
            self.service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": self._raw_mime(payload)}})
            .execute()
        )
        return created["id"]

    def send(self, payload: SendPayload) -> str:
        sent = (
            self.service.users()
            .messages()
            .send(userId="me", body={"raw": self._raw_mime(payload)})
            .execute()
        )
        return sent["id"]

    def forward(self, message_id: str, to: list[str], note: str = "") -> str:
        original = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="raw")
            .execute()
        )
        raw = base64.urlsafe_b64decode(original["raw"].encode())
        parsed = emaillib.message_from_bytes(raw)
        subject = parsed.get("Subject", "")
        body = note + "\n\n---------- forwarded message ----------\n" + (parsed.get_payload() if isinstance(parsed.get_payload(), str) else "")
        return self.send(SendPayload(to=to, subject=f"Fwd: {subject}", body=body, in_reply_to=message_id))

    def delete(self, message_id: str) -> None:
        self.service.users().messages().trash(userId="me", id=message_id).execute()

    def unsubscribe(self, message_id: str, mailto_or_url: str | None = None) -> None:
        self.apply_label(message_id, "unsubscribed")
        self.archive(message_id)
