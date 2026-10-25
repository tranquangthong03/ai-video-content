"""Demo-account credentials: encrypted at rest (Fernet), never logged, deleted when the job ends.

The key is CREDENTIAL_ENCRYPTION_KEY from the environment (.env). When it is missing a key is
generated for this process only (credentials then cannot be read after a restart, which also
ends the job) and a notice, without the key, is logged once.
"""

import json
import logging
import os
import shutil
import time
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("credentials")

CREDENTIALS_FILE = "credentials.enc"
PROFILE_DIR = "login_profile"  # the login window's browser profile (cookies of the real site)
SESSION_FILES = ("storage_state.json", "login_result.json")  # (login_report.json has no secrets)
SECRET_NAMES = {CREDENTIALS_FILE, *SESSION_FILES}  # never served by /files
OLD_JOB_S = 24 * 3600

_generated: bytes | None = None


def encryption_key(env: dict[str, str] | None = None) -> bytes:
    """The Fernet key from CREDENTIAL_ENCRYPTION_KEY, or one made for this process."""
    global _generated
    value = (env if env is not None else os.environ).get("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if value:
        return value.encode()
    if _generated is None:
        _generated = Fernet.generate_key()
        log.warning(
            "CREDENTIAL_ENCRYPTION_KEY is not set: a key was generated for this run only "
            "(set it in .env to keep demo-account credentials readable across restarts)"
        )
    return _generated


class CredentialStore:
    def __init__(self, job_dir: Path, key: bytes | None = None) -> None:
        self.path = job_dir / CREDENTIALS_FILE
        self.fernet = Fernet(key or encryption_key())

    def save(self, username: str, password: str) -> None:
        payload = json.dumps({"username": username, "password": password}).encode()
        self.path.write_bytes(self.fernet.encrypt(payload))

    def load(self) -> tuple[str, str] | None:
        try:
            data = json.loads(self.fernet.decrypt(self.path.read_bytes()))
        except (FileNotFoundError, InvalidToken, ValueError):
            return None
        return str(data["username"]), str(data["password"])

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


def cleanup_job_secrets(job_dir: Path) -> None:
    """Remove the credentials, the saved session and the login window's profile of a job."""
    for name in SECRET_NAMES:
        (job_dir / name).unlink(missing_ok=True)
    shutil.rmtree(job_dir / PROFILE_DIR, ignore_errors=True)


def sweep_old_jobs(root: Path, max_age_s: float = OLD_JOB_S) -> list[str]:
    """Clean the secrets of jobs untouched for a day (when the API starts); returns their ids."""
    cleaned: list[str] = []
    if not root.is_dir():
        return cleaned
    now = time.time()
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        has_secret = (
            any((directory / n).exists() for n in SECRET_NAMES)
            or (directory / PROFILE_DIR).exists()
        )
        if has_secret and now - directory.stat().st_mtime > max_age_s:
            cleanup_job_secrets(directory)
            cleaned.append(directory.name)
    return cleaned
