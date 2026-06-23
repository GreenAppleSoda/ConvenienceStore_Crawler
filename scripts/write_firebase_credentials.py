"""GitHub Actions용: FIREBASE_JSON 환경 변수를 credentials 파일로 저장."""
import json
import os
import sys
from pathlib import Path

CONTENT = os.environ.get("FIREBASE_JSON", "").strip()
OUT = Path("config/firebase-service-account.json")

if not CONTENT:
    print(
        "::error::FIREBASE_KEY secret is empty or not set. "
        "GitHub repo Settings > Secrets and variables > Actions에서 "
        "FIREBASE_KEY에 Firebase service account JSON 전체를 붙여넣으세요."
    )
    sys.exit(1)

try:
    json.loads(CONTENT)
except json.JSONDecodeError as exc:
    print(f"::error::FIREBASE_KEY is not valid JSON: {exc}")
    sys.exit(1)

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(CONTENT, encoding="utf-8")
print(f"Firebase credentials written ({len(CONTENT)} bytes)")
