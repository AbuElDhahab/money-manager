import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "money.db")


def _secret_key():
    """SECRET_KEY env var, else a random key generated once and kept in .secret_key."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(BASE_DIR, ".secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


SECRET_KEY = _secret_key()

GOOGLE_CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")
