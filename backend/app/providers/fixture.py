from datetime import datetime, timezone
from pathlib import Path
import json
import uuid

from app.providers.base import FetchedMessage, SendPayload

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
INBOX_PATH = FIXTURE_DIR / "inbox.json"
STATE_PATH = FIXTURE_DIR / "state.json"


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


class FixtureProvider:
    def __init__(self, account_email: str = "you@local"):
        self.account_email = account_email

    def _state(self) -> dict:
        return _load_json(STATE_PATH, {"archived": [], "deleted": [], "labels": {}, "drafts": [], "sent": []})

    def list_messages(self, since: datetime | None = None, limit: int = 50) -> list[FetchedMessage]:
        rows = _load_json(INBOX_PATH, [])
        state = self._state()
        hidden = set(state.get("archived", [])) | set(state.get("deleted", []))
        extra_labels = state.get("labels", {})
        out: list[FetchedMessage] = []
        for row in rows:
            mid = row["id"]
            if mid in hidden:
                continue
            received = datetime.fromisoformat(row["received_at"])
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
            if since and received <= since:
                continue
            labels = list(row.get("labels", []))
            labels.extend(extra_labels.get(mid, []))
            preview = row.get("preview") or row["body"][:180]
            out.append(
                FetchedMessage(
                    provider_message_id=mid,
                    subject=row.get("subject", ""),
                    sender=row["sender"],
                    to_addresses=row.get("to", [self.account_email]),
                    body_text=row["body"],
                    body_preview=preview[:500],
                    labels=labels,
                    received_at=received,
                    raw=row,
                    list_unsubscribe=row.get("list_unsubscribe"),
                )
            )
        out.sort(key=lambda m: m.received_at, reverse=True)
        return out[:limit]

    def archive(self, message_id: str) -> None:
        state = self._state()
        if message_id not in state["archived"]:
            state["archived"].append(message_id)
        _save_json(STATE_PATH, state)

    def apply_label(self, message_id: str, label: str) -> None:
        state = self._state()
        labels = state.setdefault("labels", {}).setdefault(message_id, [])
        if label not in labels:
            labels.append(label)
        _save_json(STATE_PATH, state)

    def create_draft(self, payload: SendPayload) -> str:
        state = self._state()
        draft_id = f"draft-{uuid.uuid4().hex[:10]}"
        state.setdefault("drafts", []).append(
            {
                "id": draft_id,
                "to": payload.to,
                "subject": payload.subject,
                "body": payload.body,
                "in_reply_to": payload.in_reply_to,
            }
        )
        _save_json(STATE_PATH, state)
        return draft_id

    def send(self, payload: SendPayload) -> str:
        state = self._state()
        sent_id = f"sent-{uuid.uuid4().hex[:10]}"
        state.setdefault("sent", []).append(
            {
                "id": sent_id,
                "to": payload.to,
                "subject": payload.subject,
                "body": payload.body,
                "in_reply_to": payload.in_reply_to,
            }
        )
        _save_json(STATE_PATH, state)
        return sent_id

    def forward(self, message_id: str, to: list[str], note: str = "") -> str:
        return self.send(
            SendPayload(
                to=to,
                subject=f"Fwd: {message_id}",
                body=note or f"(forwarded {message_id})",
                in_reply_to=message_id,
            )
        )

    def delete(self, message_id: str) -> None:
        state = self._state()
        if message_id not in state["deleted"]:
            state["deleted"].append(message_id)
        _save_json(STATE_PATH, state)

    def unsubscribe(self, message_id: str, mailto_or_url: str | None = None) -> None:
        self.apply_label(message_id, "unsubscribed")
        if mailto_or_url and mailto_or_url.startswith("mailto:"):
            addr = mailto_or_url.replace("mailto:", "").split("?")[0]
            self.send(SendPayload(to=[addr], subject="unsubscribe", body="unsubscribe"))
        self.archive(message_id)
