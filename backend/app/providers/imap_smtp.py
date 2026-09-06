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
from app.textutil import html_to_text

IMAP_TIMEOUT = 20
SMTP_TIMEOUT = 20


def normalize_secret(password: str) -> str:
    return (password or "").replace(" ", "").replace("\t", "").strip()


def _quote_mbox(name: str) -> str:
    if not name:
        return '""'
    if name.startswith('"') and name.endswith('"'):
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True) or b""
    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def _body_of(msg: Message) -> str:
    plain = ""
    html = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            if ctype == "text/plain" and not plain:
                plain = _decode_part(part)
            elif ctype == "text/html" and not html:
                html = _decode_part(part)
    else:
        raw = _decode_part(msg)
        if msg.get_content_type() == "text/html":
            html = raw
        else:
            plain = raw
    if plain.strip():
        if "<html" in plain.lower() or "<!doctype" in plain.lower():
            return html_to_text(plain)
        return plain.strip()
    return html_to_text(html)


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


def _fetch_raw(fetched) -> bytes | None:
    if not fetched:
        return None
    for item in fetched:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    return None


def _received_at(parsed: Message) -> datetime:
    raw = parsed.get("Date")
    if raw:
        try:
            received = parsedate_to_datetime(raw)
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
            return received
        except (TypeError, ValueError, OverflowError):
            pass
    return datetime.now(timezone.utc)


def _friendly_imap_error(exc: BaseException) -> str:
    text = str(exc).lower()
    if any(
        s in text
        for s in (
            "invalid credentials",
            "authenticationfailed",
            "application-specific password",
            "username and password not accepted",
        )
    ):
        return (
            "Gmail rejected the login. Use a 16-character App Password, not your normal "
            "password, and enable IMAP under Gmail settings > Forwarding and POP/IMAP."
        )
    if "web login required" in text or "unavailable" in text:
        return "Gmail wants a browser login first. Open Gmail in a browser, then retry."
    return f"IMAP: {exc}"


def _smtp_login(host: str, port: int, user: str, password: str) -> None:
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT) as smtp:
            smtp.login(user, password)
        return
    with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(user, password)


def test_imap_smtp(
    *,
    email_address: str,
    password: str,
    imap_host: str,
    imap_port: int,
    smtp_host: str,
    smtp_port: int,
    username: str | None = None,
) -> dict:
    password = normalize_secret(password)
    user = (username or email_address).strip()
    if not user or not password:
        raise ValueError("email and app password are required")
    if not imap_host or not smtp_host:
        raise ValueError("IMAP and SMTP hosts are required")

    conn = None
    try:
        conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=IMAP_TIMEOUT)
        typ, _ = conn.login(user, password)
        if typ != "OK":
            raise ValueError("IMAP login failed")
        sel, _ = conn.select("INBOX", readonly=True)
        if sel != "OK":
            raise ValueError(
                "IMAP logged in but could not open INBOX. Enable IMAP in Gmail settings."
            )
    except ValueError:
        raise
    except imaplib.IMAP4.error as exc:
        raise ValueError(_friendly_imap_error(exc)) from exc
    except OSError as exc:
        raise ValueError(f"Could not reach {imap_host}:{imap_port} ({exc})") from exc
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass

    try:
        _smtp_login(smtp_host, smtp_port, user, password)
    except smtplib.SMTPAuthenticationError as exc:
        raise ValueError(
            "IMAP worked, SMTP login failed. For Gmail, the same App Password should work on both."
        ) from exc
    except OSError as exc:
        raise ValueError(f"Could not reach {smtp_host}:{smtp_port} ({exc})") from exc
    except smtplib.SMTPException as exc:
        raise ValueError(f"SMTP: {exc}") from exc

    return {"ok": True, "imap": True, "smtp": True}


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
        self.password = normalize_secret(creds["password"])
        self.imap_host = imap_host
        self.imap_port = imap_port or 993
        self.smtp_host = smtp_host or imap_host
        self.smtp_port = smtp_port or 587
        self.email_address = email_address

    def _imap(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=IMAP_TIMEOUT)
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
            if '"' in line:
                names.append(line.rsplit('"', 2)[-2])
            else:
                names.append(line.split()[-1])
        lower = {n.lower(): n for n in names}
        for cand in candidates:
            if cand.lower() in lower:
                return lower[cand.lower()]
        return None

    def _uid_ids(self, data) -> list[bytes]:
        if not data or not data[0]:
            return []
        return data[0].split()

    def list_messages(
        self,
        since: datetime | None = None,
        limit: int = 50,
        skip_ids: set[str] | None = None,
    ) -> list[FetchedMessage]:
        conn = self._imap()
        try:
            typ, _ = conn.select("INBOX", readonly=True)
            if typ != "OK":
                return []
            max_uid = None
            if skip_ids:
                nums = []
                for x in skip_ids:
                    try:
                        nums.append(int(x))
                    except (TypeError, ValueError):
                        continue
                if nums:
                    max_uid = max(nums)
            if max_uid is not None:
                typ, data = conn.uid("SEARCH", None, f"UID {max_uid + 1}:*")
            elif since:
                typ, data = conn.uid("SEARCH", None, since.strftime("SINCE %d-%b-%Y"))
            else:
                typ, data = conn.uid("SEARCH", None, "ALL")
            if typ != "OK":
                return []
            ids = self._uid_ids(data)
            if not ids:
                return []
            ids = ids[-limit:]
            out: list[FetchedMessage] = []
            for msgid in reversed(ids):
                uid = msgid.decode() if isinstance(msgid, bytes) else str(msgid)
                if skip_ids and uid in skip_ids:
                    continue
                typ, fetched = conn.uid("FETCH", msgid, "(BODY.PEEK[])")
                if typ != "OK":
                    continue
                blob = _fetch_raw(fetched)
                if not blob:
                    continue
                parsed = emaillib.message_from_bytes(blob)
                body = _body_of(parsed)
                unsub = parsed.get("List-Unsubscribe")
                out.append(
                    FetchedMessage(
                        provider_message_id=uid,
                        subject=_decode_hdr(parsed.get("Subject")),
                        sender=_decode_hdr(parsed.get("From")),
                        to_addresses=[_decode_hdr(parsed.get("To"))],
                        body_text=body.strip(),
                        body_preview=body.strip()[:500],
                        labels=["INBOX"],
                        received_at=_received_at(parsed),
                        raw={"imap_uid": uid},
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
            dest = self._pick_folder(conn, ["[Gmail]/All Mail", "Archive", "Archives", "Archived"])
            if dest:
                try:
                    conn.uid("COPY", message_id, _quote_mbox(dest))
                except imaplib.IMAP4.error:
                    pass
            typ, _ = conn.uid("STORE", message_id, "+FLAGS", "(\\Deleted)")
            if typ != "OK":
                raise RuntimeError(f"could not archive {message_id}")
            conn.expunge()
        finally:
            conn.logout()

    def apply_label(self, message_id: str, label: str) -> None:
        conn = self._imap()
        try:
            conn.select("INBOX")
            dest = self._pick_folder(conn, [label])
            if not dest:
                conn.create(_quote_mbox(label))
                dest = label
            conn.uid("COPY", message_id, _quote_mbox(dest))
        finally:
            conn.logout()

    def _smtp_send(self, msg: MIMEText) -> None:
        if self.smtp_port == 465:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=SMTP_TIMEOUT) as smtp:
                smtp.login(self.user, self.password)
                smtp.send_message(msg)
            return
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=SMTP_TIMEOUT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
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
            dest = self._pick_folder(conn, ["[Gmail]/Drafts", "Drafts", "INBOX.Drafts"])
            if dest:
                conn.append(_quote_mbox(dest), "\\Draft", None, msg.as_bytes())
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
            conn.select("INBOX", readonly=True)
            typ, fetched = conn.uid("FETCH", message_id, "(BODY.PEEK[])")
            body = note
            subj = message_id
            blob = _fetch_raw(fetched) if typ == "OK" else None
            if blob:
                parsed = emaillib.message_from_bytes(blob)
                subj = _decode_hdr(parsed.get("Subject"))
                body = (note + "\n\n---------- forwarded message ----------\n" + _body_of(parsed)).strip()
        finally:
            conn.logout()
        return self.send(SendPayload(to=to, subject=f"Fwd: {subj}", body=body, in_reply_to=message_id))

    def delete(self, message_id: str) -> None:
        conn = self._imap()
        try:
            conn.select("INBOX")
            conn.uid("STORE", message_id, "+FLAGS", "(\\Deleted)")
            conn.expunge()
        finally:
            conn.logout()

    def unsubscribe(self, message_id: str, mailto_or_url: str | None = None) -> None:
        if mailto_or_url and mailto_or_url.lower().startswith("mailto:"):
            addr = mailto_or_url.replace("mailto:", "").split("?")[0]
            self.send(SendPayload(to=[addr], subject="unsubscribe", body="unsubscribe"))
        self.archive(message_id)
