from datetime import datetime, timezone
import re

import httpx
import msal

from app.config import settings
from app.crypto import decrypt_json, encrypt_json
from app.providers.base import FetchedMessage, SendPayload

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.ReadWrite", "Mail.Send", "offline_access", "User.Read"]


def _app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        settings.microsoft_client_id,
        authority=f"https://login.microsoftonline.com/{settings.microsoft_tenant}",
        client_credential=settings.microsoft_client_secret,
    )


def refresh_tokens(encrypted: str) -> tuple[dict, str]:
    data = decrypt_json(encrypted)
    result = _app().acquire_token_by_refresh_token(data["refresh_token"], scopes=SCOPES)
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description") or "outlook token refresh failed")
    data["access_token"] = result["access_token"]
    if result.get("refresh_token"):
        data["refresh_token"] = result["refresh_token"]
    expires_in = int(result.get("expires_in") or 3600)
    data["expires_at"] = (datetime.now(timezone.utc).timestamp() + expires_in - 60)
    return data, encrypt_json(data)


class OutlookProvider:
    def __init__(self, tokens_encrypted: str):
        self.tokens = decrypt_json(tokens_encrypted)
        if self._needs_refresh():
            self.tokens, self._blob = refresh_tokens(tokens_encrypted)
        else:
            self._blob = tokens_encrypted

    def _needs_refresh(self) -> bool:
        exp = self.tokens.get("expires_at")
        if not exp:
            return True
        try:
            when = float(exp)
        except (TypeError, ValueError):
            return True
        return when <= datetime.now(timezone.utc).timestamp()

    def refreshed_blob(self) -> str:
        return self._blob

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens['access_token']}"}

    def list_messages(self, since: datetime | None = None, limit: int = 50) -> list[FetchedMessage]:
        params: dict[str, str] = {
            "$top": str(min(limit, 50)),
            "$orderby": "receivedDateTime DESC",
            "$select": "id,subject,from,toRecipients,bodyPreview,body,receivedDateTime,categories,internetMessageHeaders",
        }
        if since:
            iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            params["$filter"] = f"receivedDateTime ge {iso}"
        with httpx.Client(timeout=30) as client:
            r = client.get(f"{GRAPH}/me/messages", headers=self._h(), params=params)
            r.raise_for_status()
            rows = r.json().get("value") or []
        out: list[FetchedMessage] = []
        for row in rows:
            frm = row.get("from") or {}
            addr = frm.get("emailAddress") or {}
            name, address = addr.get("name") or "", addr.get("address") or ""
            sender = f"{name} <{address}>" if name else address
            to_addrs = [
                (t.get("emailAddress") or {}).get("address") or ""
                for t in row.get("toRecipients") or []
            ]
            received = datetime.fromisoformat(row["receivedDateTime"].replace("Z", "+00:00"))
            body_obj = row.get("body") or {}
            body_text = body_obj.get("content") or ""
            if (body_obj.get("contentType") or "").lower() == "html":
                body_text = re.sub(r"<[^>]+>", " ", body_text)
            headers = {h["name"].lower(): h["value"] for h in row.get("internetMessageHeaders") or []}
            out.append(
                FetchedMessage(
                    provider_message_id=row["id"],
                    subject=row.get("subject") or "",
                    sender=sender,
                    to_addresses=[a for a in to_addrs if a],
                    body_text=body_text.strip(),
                    body_preview=(row.get("bodyPreview") or "")[:500],
                    labels=row.get("categories") or [],
                    received_at=received,
                    raw={"id": row["id"]},
                    list_unsubscribe=headers.get("list-unsubscribe"),
                )
            )
        return out

    def archive(self, message_id: str) -> None:
        with httpx.Client(timeout=30) as client:
            r = client.post(
                f"{GRAPH}/me/messages/{message_id}/move",
                headers=self._h(),
                json={"destinationId": "archive"},
            )
            r.raise_for_status()

    def apply_label(self, message_id: str, label: str) -> None:
        with httpx.Client(timeout=30) as client:
            got = client.get(
                f"{GRAPH}/me/messages/{message_id}",
                headers=self._h(),
                params={"$select": "categories"},
            )
            got.raise_for_status()
            cats = list(got.json().get("categories") or [])
            if label not in cats:
                cats.append(label)
            r = client.patch(
                f"{GRAPH}/me/messages/{message_id}",
                headers=self._h(),
                json={"categories": cats},
            )
            r.raise_for_status()

    def create_draft(self, payload: SendPayload) -> str:
        body = {
            "subject": payload.subject,
            "body": {"contentType": "Text", "content": payload.body},
            "toRecipients": [{"emailAddress": {"address": a}} for a in payload.to],
        }
        if payload.cc:
            body["ccRecipients"] = [{"emailAddress": {"address": a}} for a in payload.cc]
        with httpx.Client(timeout=30) as client:
            r = client.post(f"{GRAPH}/me/messages", headers=self._h(), json=body)
            r.raise_for_status()
            return r.json()["id"]

    def send(self, payload: SendPayload) -> str:
        draft_id = self.create_draft(payload)
        with httpx.Client(timeout=30) as client:
            r = client.post(f"{GRAPH}/me/messages/{draft_id}/send", headers=self._h())
            r.raise_for_status()
        return draft_id

    def forward(self, message_id: str, to: list[str], note: str = "") -> str:
        with httpx.Client(timeout=30) as client:
            r = client.post(
                f"{GRAPH}/me/messages/{message_id}/forward",
                headers=self._h(),
                json={
                    "comment": note,
                    "toRecipients": [{"emailAddress": {"address": a}} for a in to],
                },
            )
            r.raise_for_status()
        return message_id

    def delete(self, message_id: str) -> None:
        with httpx.Client(timeout=30) as client:
            r = client.delete(f"{GRAPH}/me/messages/{message_id}", headers=self._h())
            r.raise_for_status()

    def unsubscribe(self, message_id: str, mailto_or_url: str | None = None) -> None:
        self.apply_label(message_id, "unsubscribed")
        self.archive(message_id)
