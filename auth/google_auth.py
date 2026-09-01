"""Google OAuth 2.0 (installed-app flow) for read-only Calendar access.

Design choices made for security, not just convenience:

* SCOPES is read-only and nothing else. Never widen this without updating
  SECURITY.md — a broader scope is the single biggest backdoor risk in an
  app like this.
* By default every copy of the built app shares ONE client_secret.json,
  bundled in at build time by whoever packages the app (see
  config.client_secret_path and README section 5) — that's a deliberate
  convenience trade-off (nobody who receives the app touches Google Cloud
  Console) documented in SECURITY.md, including how to opt out per-install
  via Settings > Account if isolation matters more than convenience for a
  given deployment.
* Tokens never touch disk in plaintext — see token_store.py.
* This module never logs token contents.
"""

from __future__ import annotations

import logging
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from auth import token_store

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class AuthError(Exception):
    pass


def _load_cached_credentials() -> Credentials | None:
    raw = token_store.load_token()
    if not raw:
        return None
    try:
        return Credentials.from_authorized_user_info(_json_loads(raw), SCOPES)
    except Exception:
        logger.warning("Stored credentials were unreadable; discarding.")
        token_store.clear_token()
        return None


def _json_loads(raw: str) -> dict:
    import json

    return json.loads(raw)


def get_credentials(client_secret_path: Path) -> Credentials:
    """Return valid credentials, refreshing or launching the browser-based
    consent flow only when necessary."""
    creds = _load_cached_credentials()

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_store.save_token(creds.to_json())
            return creds
        except RefreshError:
            logger.info("Refresh token no longer valid; re-authentication required.")
            token_store.clear_token()

    if not client_secret_path.exists():
        raise AuthError(
            "This copy of Calendar Reminder is missing its Google credentials file "
            f"(looked for client_secret.json at {client_secret_path}). "
            "If you built this app yourself, see README.md sections 1, 3, and 6 — "
            "the file needs to sit next to app.py (or next to the .exe) before packaging, "
            "or be added via Settings > Account > 'Use my own Google credentials'."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    # Loopback redirect on an OS-assigned port — no fixed port to collide
    # with or expose, and never uses the deprecated out-of-band flow.
    creds = flow.run_local_server(port=0)

    granted = set(creds.scopes or [])
    if not granted.issubset(set(SCOPES)) and not granted == set(SCOPES):
        # Google may return scopes in a different order/format; only object
        # if something outside our requested set was granted.
        extra = granted - set(SCOPES)
        if extra:
            raise AuthError(f"Unexpected OAuth scopes granted: {extra}")

    token_store.save_token(creds.to_json())
    return creds


def sign_out() -> None:
    token_store.clear_token()


def is_signed_in() -> bool:
    return _load_cached_credentials() is not None
