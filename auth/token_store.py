"""Secure storage for the OAuth refresh/access token.

Tokens are kept in the OS credential store (Windows Credential Manager via
`keyring`, backed by DPAPI) instead of a plaintext file on disk. Never log
or print the token value anywhere in this module.
"""

from __future__ import annotations

import keyring

_SERVICE_NAME = "CalendarReminderApp"
_USERNAME = "google_oauth_credentials"


def save_token(token_json: str) -> None:
    keyring.set_password(_SERVICE_NAME, _USERNAME, token_json)


def load_token() -> str | None:
    return keyring.get_password(_SERVICE_NAME, _USERNAME)


def clear_token() -> None:
    try:
        keyring.delete_password(_SERVICE_NAME, _USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
