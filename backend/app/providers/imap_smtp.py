from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
import email as emaillib
import imaplib
import smtplib
import uuid

from app.crypto import decrypt_json
from app.providers.base import FetchedMessage, SendPayload


def _decode_hdr(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(chunk)
    return "".join(out)


def _body_of(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


class ImapSmtpProvider:
    def __init__(
        self,
        credentials_encrypted: str,
        imap_host: str,
        imap_port: int | None,
        smtp_host: str | None,
        smtp_port: int | None,
        email_address: str,
    ):
        creds = decrypt_json(credentials_encrypted)
        self.user = creds.get("username") or email_address
        self.password = creds["password"]
        self.imap_host = imap_host
        self.imap_port = imap_port or 993
        self.smtp_host = smtp_host or imap_host
        self.smtp_port = smtp_port or 587
        self.email_address = email_address

    def _imap(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        conn.login(self.user, self.password)
        return conn

    def _pick_folder(self, conn: imaplib.IMAP4_SSL, candidates: list[str]) -> str | None:
        typ, boxes = conn.list()
        if typ != "OK" or not boxes:
            return None
        names = []
        for raw in boxes:
            if not raw:
                continue
            line = raw.decode() if isinstance(raw, bytes) else str(raw)
            # last quoted token is the mailbox name
            if '"' in line:
                names.append(line.rsplit('"', 2)[-2])
            else:
                names.append(line.split()[-1])
        lower = {n.lower(): n for n in names}
        for cand in candidates:
            if cand.lower() in lower:
                return lower[cand.lower()]
        return None

    def list_messages(self, since: datetime | None = None, limit: int = 50) -> list[FetchedMessage]:
        conn = self._imap()
        try:
            typ, _ = conn.select("INBOX")
            if typ != "OK":
                return []
            if since:
                criteria = since.strftime("SINCE %d-%b-%Y")
                typ, data = conn.search(None, criteria)
            else:
                typ, data = conn.search(None, "ALL")
            if typ != "OK" or not data or not data[0]:
                return []
            ids = data[0].split()
            if not ids:
                return []
            ids = ids[-limit:]
            out: list[FetchedMessage] = []
            for msgid in reversed(ids):
                typ, fetched = conn.fetch(msgid, "(RFC822)")
                if typ != "OK" or not fetched or fetched[0] is None:
                    continue
                blob = fetched[0][1]
                parsed = emaillib.message_from_bytes(blob)
                received = parsedate_to_datetime(parsed.get("Date") or "")
                if received.tzinfo is None:
                    received = received.replace(tzinfo=timezone.utc)
                body = _body_of(parsed)
                unsub = parsed.get("List-Unsubscribe")
                out.append(
                    FetchedMessage(
                        provider_message_id=msgid.decode() if isinstance(msgid, bytes) else str(msgid),
                        subject=_decode_hdr(parsed.get("Subject")),
                        sender=_decode_hdr(parsed.get("From")),
                        to_addresses=[_decode_hdr(parsed.get("To"))],
                        body_text=body.strip(),
                        body_preview=body.strip()[:500],
                        labels=["INBOX"],
                        received_at=received,
                        raw={"imap_uid": msgid.decode() if isinstance(msgid, bytes) else str(msgid)},
                        list_unsubscribe=unsub,
                    )
                )
            return out
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def archive(self, message_id: str) -> None:
        conn = self._imap()
        try:
            conn.select("INBOX")
            dest = self._pick_folder(conn, ["Archive", "Archives", "Archived", "[Gmail]/All Mail"])
            if dest:
                conn.copy(message_id, dest)
            conn.store(message_id, "+FLAGS", "\\Deleted")
            conn.expunge()
        finally:
            conn.logout()

    def apply_label(self, message_id: str, label: str) -> None:
        conn = self._imap()
        try:
            conn.select("INBOX")
            dest = self._pick_folder(conn, [label])
            if not dest:
                conn.create(label)
                dest = label
            conn.copy(message_id, dest)
        finally:
            conn.logout()

    def _smtp_send(self, msg: MIMEText) -> None:
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.send_message(msg)

    def create_draft(self, payload: SendPayload) -> str:
        draft_id = f"imap-draft-{uuid.uuid4().hex[:10]}"
        msg = MIMEText(payload.body, "plain", "utf-8")
        msg["From"] = self.email_address
        msg["To"] = ", ".join(payload.to)
        msg["Subject"] = payload.subject
        conn = self._imap()
        try:
            dest = self._pick_folder(conn, ["Drafts", "[Gmail]/Drafts", "INBOX.Drafts"])
            if dest:
                conn.append(dest, "\\Draft", None, msg.as_bytes())
        finally:
            conn.logout()
        return draft_id

    def send(self, payload: SendPayload) -> str:
        msg = MIMEText(payload.body, "plain", "utf-8")
        msg["From"] = self.email_address
        msg["To"] = ", ".join(payload.to)
        msg["Subject"] = payload.subject
        if payload.in_reply_to:
            msg["In-Reply-To"] = payload.in_reply_to
        self._smtp_send(msg)
        return f"smtp-{uuid.uuid4().hex[:10]}"

    def forward(self, message_id: str, to: list[str], note: str = "") -> str:
        conn = self._imap()
        try:
            conn.select("INBOX")
            typ, fetched = conn.fetch(message_id, "(RFC822)")
            body = note
            subj = message_id
            if typ == "OK" and fetched and fetched[0]:
                parsed = emaillib.message_from_bytes(fetched[0][1])
                subj = _decode_hdr(parsed.get("Subject"))
                body = (note + "\n\n---------- forwarded message ----------\n" + _body_of(parsed)).strip()
        finally:
            conn.logout()
        return self.send(SendPayload(to=to, subject=f"Fwd: {subj}", body=body, in_reply_to=message_id))

    def delete(self, message_id: str) -> None:
        conn = self._imap()
        try:
            conn.select("INBOX")
            conn.store(message_id, "+FLAGS", "\\Deleted")
            conn.expunge()
        finally:
            conn.logout()

    def unsubscribe(self, message_id: str, mailto_or_url: str | None = None) -> None:
        if mailto_or_url and mailto_or_url.lower().startswith("mailto:"):
            addr = mailto_or_url.replace("mailto:", "").split("?")[0]
            self.send(SendPayload(to=[addr], subject="unsubscribe", body="unsubscribe"))
        self.archive(message_id)
