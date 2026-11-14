"""Admin password hashing, signed browser sessions, login throttle."""

from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass
import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
import time

ITERATIONS = 600_000
SESSION_SECONDS = 8 * 60 * 60
SESSION_COOKIE = "__Secure-onedrive-admin"
LOGIN_COOKIE = "__Secure-onedrive-login"


class AuthError(Exception):
    """Authentication files missing, corrupt or unsafe."""


def enc(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def dec(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _parse_record(record: str) -> tuple[int, bytes, bytes]:
    try:
        algorithm, count, salt64, digest64 = record.strip().split("$")
        count = int(count)
        salt, digest = dec(salt64), dec(digest64)
        if algorithm != "pbkdf2-sha256" or not 400_000 <= count <= 2_000_000 or len(salt) < 16 or len(digest) != 32:
            raise ValueError("format")
        return count, salt, digest
    except (TypeError, ValueError) as exc:
        raise AuthError("Недопустимый формат хеша пароля") from exc


def password_hash(password: str) -> str:
    if len(password) < 12 or len(password.encode("utf-8")) > 4096:
        raise ValueError("Пароль должен содержать не менее 12 символов")
    salt = secrets.token_bytes(24)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "pbkdf2-sha256$" + str(ITERATIONS) + "$" + enc(salt) + "$" + enc(digest)


def verify_password(password: str, record: str) -> bool:
    count, salt, expected = _parse_record(record)
    if len(password.encode("utf-8")) > 4096:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, count)
    return hmac.compare_digest(expected, digest)


def load_record(filename: Path) -> str:
    try:
        if filename.is_symlink():
            raise AuthError("Файл хеша не может быть символической ссылкой")
        st = filename.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
            raise AuthError("Файл хеша должен иметь права 0600")
        data = filename.read_text(encoding="ascii").strip()
        _parse_record(data)
        return data
    except (OSError, UnicodeError) as exc:
        raise AuthError("Файл admin-password.hash отсутствует либо недоступен") from exc


def save_record(filename: Path, record: str) -> None:
    _parse_record(record)
    if filename.parent.is_symlink() or filename.is_symlink():
        raise AuthError("Небезопасная символическая ссылка")
    filename.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staged = None
    try:
        fd, staged = tempfile.mkstemp(prefix=".admin-", dir=filename.parent)
        with os.fdopen(fd, "w", encoding="ascii") as fp:
            fp.write(record + "\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.chmod(staged, 0o600)
        os.replace(staged, filename)
    finally:
        if staged and os.path.exists(staged):
            os.unlink(staged)


def signature(record: str, body: str) -> str:
    key = hashlib.sha256(b"onedrive-cookie-v1\0" + record.encode()).digest()
    return enc(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())


def issue_session(record: str) -> tuple[str, str]:
    csrf = secrets.token_urlsafe(32)
    payload = {"user": "admin", "exp": int(time.time()) + SESSION_SECONDS,
               "csrf": csrf, "nonce": secrets.token_hex(16)}
    body = enc(json.dumps(payload, separators=(",", ":")).encode())
    return body + "." + signature(record, body), csrf


def authenticate_session(record: str, cookie: str | None) -> dict | None:
    if not cookie or len(cookie) > 4096:
        return None
    try:
        body, mac = cookie.split(".")
        if not hmac.compare_digest(signature(record, body), mac):
            return None
        state = json.loads(dec(body))
        now = int(time.time())
        if (state.get("user") != "admin" or type(state.get("exp")) is not int
                or not now < state["exp"] <= now + SESSION_SECONDS
                or not isinstance(state.get("csrf"), str)
                or len(state["csrf"]) < 20):
            return None
        return state
    except (ValueError, TypeError, KeyError, UnicodeError):
        return None


@dataclass
class Throttle:
    max_attempts: int = 5
    window: int = 900

    def __post_init__(self) -> None:
        self.attempts: dict[str, deque[float]] = defaultdict(deque)

    def allowed(self, peer: str) -> bool:
        now = time.monotonic()
        recent = self.attempts[peer]
        while recent and recent[0] < now - self.window:
            recent.popleft()
        return len(recent) < self.max_attempts

    def failed(self, peer: str) -> None:
        self.attempts[peer].append(time.monotonic())

    def succeeded(self, peer: str) -> None:
        self.attempts.pop(peer, None)


def change_admin_password(filename: Path) -> None:
    first = getpass.getpass("Новый пароль admin (не менее 12 символов): ")
    second = getpass.getpass("Повторите пароль: ")
    if first != second:
        raise ValueError("Пароли не совпадают")
    save_record(filename, password_hash(first))


def main() -> int:
    parser = argparse.ArgumentParser(description="Задать пароль администратора OneDrive Backup")
    parser.add_argument("--file", type=Path, default=Path("/etc/onedrive-backup/admin-password.hash"))
    args = parser.parse_args()
    try:
        change_admin_password(args.file)
    except (ValueError, OSError, AuthError) as exc:
        parser.exit(1, str(exc) + "\n")
    print("Хеш пароля admin сохранён; старые сессии недействительны.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

