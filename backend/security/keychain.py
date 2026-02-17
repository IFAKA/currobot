"""OS credential storage via `keyring` (macOS Keychain, Windows Credential Manager, Linux Secret Service). Never plaintext in DB or files."""
from __future__ import annotations

from typing import Optional

import keyring
import structlog

log = structlog.get_logger(__name__)

SERVICE_NAME = "jobbot"


def store_credential(site: str, username: str, password: str) -> None:
    """Store credentials for a site in the system keychain."""
    key = f"{SERVICE_NAME}/{site}/{username}"
    keyring.set_password(SERVICE_NAME, key, password)
    log.info("keychain.stored", site=site, username=username)


def get_credential(site: str, username: str) -> Optional[str]:
    """Retrieve a credential. Returns None if not found."""
    key = f"{SERVICE_NAME}/{site}/{username}"
    password = keyring.get_password(SERVICE_NAME, key)
    if password is None:
        log.warning("keychain.not_found", site=site, username=username)
    return password


def delete_credential(site: str, username: str) -> None:
    """Remove a credential from the keychain."""
    key = f"{SERVICE_NAME}/{site}/{username}"
    try:
        keyring.delete_password(SERVICE_NAME, key)
        log.info("keychain.deleted", site=site, username=username)
    except keyring.errors.PasswordDeleteError:
        log.warning("keychain.delete_not_found", site=site, username=username)


def has_credential(site: str, username: str) -> bool:
    return get_credential(site, username) is not None
