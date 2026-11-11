"""Who is calling. The browser signs in with Firebase Auth (Google sign-in; Identity Platform in
production) and sends the ID token as `Authorization: Bearer <token>`. We verify it with
firebase-admin, then find or create the user's row. Locally the token comes from the Firebase Auth
emulator in compose.yaml; firebase-admin verifies emulator tokens when FIREBASE_AUTH_EMULATOR_HOST
is set. The code path is the same in both places.

No token means an anonymous visitor: they can browse and ask a few questions, and nothing is saved.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import firebase_admin
from fastapi import HTTPException, Request
from firebase_admin import auth as fb_auth

import config
import db

_app = None


def _firebase():
    global _app
    if _app is None:
        if config.AUTH_EMULATOR:
            # the emulator needs no credentials, only a project id
            _app = firebase_admin.initialize_app(
                credential=_NoCredential(), options={"projectId": config.FIREBASE_PROJECT})
        else:
            _app = firebase_admin.initialize_app(options={"projectId": config.FIREBASE_PROJECT})
    return _app


class _NoCredential(firebase_admin.credentials.Base):
    def get_credential(self):
        from google.auth.credentials import AnonymousCredentials

        return AnonymousCredentials()


@dataclass
class Caller:
    user: dict | None  # users row when signed in
    who: str  # usage-limit key: user id, or a hash of address + browser id for anonymous visitors
    net: str | None = None  # anonymous only: a hash of the address alone, for a looser per-network cap

    @property
    def signed_in(self) -> bool:
        return self.user is not None

    @property
    def kind(self) -> str:
        return "user" if self.user else "anon"


def caller(request: Request) -> Caller:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer ") and db.enabled():
        token = header[7:].strip()
        try:
            claims = fb_auth.verify_id_token(token, app=_firebase())
        except Exception as e:  # noqa: BLE001
            raise HTTPException(401, f"Sign-in expired or invalid: {type(e).__name__}") from e
        user = db.upsert_user(claims["uid"], claims.get("email"), claims.get("name"))
        return Caller(user=user, who=str(user["id"]))
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0]
    # One campus network shares an address, so the limit is per browser (a random id the page keeps),
    # with a looser cap per address so clearing storage doesn't give unlimited use.
    browser = request.headers.get("x-oversight-client", "")[:64]
    h = lambda v: hashlib.sha256(v.encode()).hexdigest()[:16]  # noqa: E731
    return Caller(user=None, who="anon:" + h(ip + "|" + browser), net="net:" + h(ip))


def require_user(request: Request) -> Caller:
    c = caller(request)
    if not c.signed_in:
        raise HTTPException(401, "Sign in to use this.")
    return c
