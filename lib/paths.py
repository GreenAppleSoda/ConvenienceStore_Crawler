import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
ENV_FILE = PROJECT_ROOT / ".env"

FIREBASE_CREDENTIAL_FILENAME = "firebase-service-account.json"


def get_firebase_credentials_path() -> Path:
    env_path = os.environ.get("FIREBASE_CREDENTIALS", "").strip()
    if env_path:
        return Path(env_path)

    config_path = CONFIG_DIR / FIREBASE_CREDENTIAL_FILENAME
    if config_path.is_file():
        return config_path

    root_path = PROJECT_ROOT / FIREBASE_CREDENTIAL_FILENAME
    if root_path.is_file():
        return root_path

    return config_path
