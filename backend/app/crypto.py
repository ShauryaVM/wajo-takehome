import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    raw = settings.fernet_key.strip()
    if not raw:
        digest = hashlib.sha256(settings.secret_key.encode()).digest()
        raw = base64.urlsafe_b64encode(digest).decode()
    if isinstance(raw, str):
        raw = raw.encode()
    return Fernet(raw)


def encrypt_json(data: dict) -> str:
    blob = json.dumps(data).encode()
    return _fernet().encrypt(blob).decode()


def decrypt_json(token: str) -> dict:
    try:
        raw = _fernet().decrypt(token.encode())
    except InvalidToken as exc:
        raise ValueError("could not decrypt credentials") from exc
    return json.loads(raw.decode())
