from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class FetchedMessage:
    provider_message_id: str
    subject: str
    sender: str
    to_addresses: list[str]
    body_text: str
    body_preview: str
    labels: list[str]
    received_at: datetime
    raw: dict[str, Any]
    list_unsubscribe: str | None = None


@dataclass
class SendPayload:
    to: list[str]
    subject: str
    body: str
    in_reply_to: str | None = None
    cc: list[str] = field(default_factory=list)


class EmailProvider(Protocol):
    def list_messages(self, since: datetime | None = None, limit: int = 50) -> list[FetchedMessage]:
        ...

    def archive(self, message_id: str) -> None:
        ...

    def apply_label(self, message_id: str, label: str) -> None:
        ...

    def create_draft(self, payload: SendPayload) -> str:
        ...

    def send(self, payload: SendPayload) -> str:
        ...

    def forward(self, message_id: str, to: list[str], note: str = "") -> str:
        ...

    def delete(self, message_id: str) -> None:
        ...

    def unsubscribe(self, message_id: str, mailto_or_url: str | None = None) -> None:
        ...
