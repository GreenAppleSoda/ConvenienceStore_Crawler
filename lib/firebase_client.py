import firebase_admin
from firebase_admin import credentials, firestore

from lib.paths import get_firebase_credentials_path

_db = None


def get_firestore_client():
    global _db
    if _db is not None:
        return _db

    cred_path = get_firebase_credentials_path()
    if not cred_path.is_file():
        raise RuntimeError(
            f"Firebase credentials 파일을 찾을 수 없습니다: {cred_path}\n"
            "config/ 에 JSON을 두거나 FIREBASE_CREDENTIALS 환경 변수를 설정하세요."
        )

    if not firebase_admin._apps:
        cred = credentials.Certificate(str(cred_path))
        firebase_admin.initialize_app(cred)

    _db = firestore.client()
    return _db
