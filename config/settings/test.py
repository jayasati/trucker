"""Test settings: swap Postgres for local SQLite so the suite runs without Docker.

Nothing under test relies on Postgres-specific SQL — this only affects how the
test database is provisioned, not the production/dev stack (see SPEC.md).
"""

from .base import *  # noqa: F401,F403

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
