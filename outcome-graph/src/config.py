"""Settings, all from the environment. The same image runs locally and on Cloud Run; only these
values change. Nothing here is a secret except DATABASE_URL's password, which comes from Secret
Manager in production and from compose.yaml locally."""

from __future__ import annotations

import os
from pathlib import Path


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default) not in ("0", "false", "False", "")


DATA_ROOT = Path(os.environ["OUTCOME_DATA_ROOT"]) if os.environ.get("OUTCOME_DATA_ROOT") else None
DEFAULT_DOCKET = os.environ.get("DOCKET", "EPA-HQ-OW-2022-0801")

# Postgres. Unset means no accounts: the page still works, signed-out only.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Firebase Auth / Identity Platform. Locally FIREBASE_AUTH_EMULATOR_HOST points at the emulator in
# compose.yaml and the project id is a "demo-" one, so nothing touches a real Google project.
FIREBASE_PROJECT = os.environ.get("FIREBASE_PROJECT", "demo-oversight")
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "demo-key")  # a public client id, not a secret
FIREBASE_AUTH_DOMAIN = os.environ.get("FIREBASE_AUTH_DOMAIN", f"{FIREBASE_PROJECT}.firebaseapp.com")
AUTH_EMULATOR = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", "")
AUTH_EMULATOR_PUBLIC = os.environ.get("AUTH_EMULATOR_PUBLIC", "http://127.0.0.1:9099")

# The model. "vertex": Claude on Vertex AI, authenticated with Google credentials (gcloud login
# locally, the Cloud Run service account in production). No Anthropic API key exists anywhere.
# "cli": the laptop's Claude Code login, a development fallback only.
LLM_BACKEND = os.environ.get("LLM_BACKEND", "vertex")
GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "ac215-undersigned")
VERTEX_REGION = os.environ.get("VERTEX_REGION", "global")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
CLI_MODEL = os.environ.get("CLI_MODEL", "sonnet")
AGENT = _flag("AGENT", "1")

# Iris's voice: Google Cloud Text-to-Speech, Chirp 3 HD, with the same Google credentials.
TTS_VOICE = os.environ.get("TTS_VOICE", "en-US-Chirp3-HD-Aoede")

# Daily model-call limits.
NET_FACTOR = int(os.environ.get("NET_FACTOR", "8"))  # per-address cap = this x the per-browser limit
LIMITS = {
    ("anon", "ask"): int(os.environ.get("ANON_ASKS", "5")),
    ("anon", "coach"): int(os.environ.get("ANON_COACH", "2")),
    ("user", "ask"): int(os.environ.get("USER_ASKS", "60")),
    ("user", "coach"): int(os.environ.get("USER_COACH", "15")),
    ("anon", "speak"): int(os.environ.get("ANON_SPEAK", "40")),
    ("user", "speak"): int(os.environ.get("USER_SPEAK", "300")),
}
