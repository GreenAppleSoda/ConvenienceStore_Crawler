# Firestore 컬렉션 전체 삭제 유틸
# 웹 콘솔에서 삭제가 안 될 때, 문서를 배치로 지워 컬렉션을 비웁니다.
#
# 사용:
#   .\.venv\Scripts\python.exe scripts\delete_firestore_collection.py
#   .\.venv\Scripts\python.exe scripts\delete_firestore_collection.py --collection "다른이름"

import argparse

import lib._bootstrap  # noqa: F401
from lib.firebase_client import get_firestore_client

DEFAULT_COLLECTION = "7-ELEVEN_events"
BATCH_SIZE = 400


def delete_collection(collection_name):
    collection_ref = db.collection(collection_name)
    total_deleted = 0

    while True:
        docs = list(collection_ref.limit(BATCH_SIZE).stream())
        if not docs:
            break

        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)

        batch.commit()
        total_deleted += len(docs)
        print(f"  - {len(docs)}개 문서 삭제 (누적 {total_deleted}개)")

    return total_deleted


db = get_firestore_client()

parser = argparse.ArgumentParser(description="Firestore 컬렉션의 모든 문서 삭제")
parser.add_argument(
    "--collection",
    default=DEFAULT_COLLECTION,
    help=f"삭제할 컬렉션 이름 (기본: {DEFAULT_COLLECTION})",
)
args = parser.parse_args()

collection_name = args.collection.strip()
if not collection_name:
    raise SystemExit("컬렉션 이름이 비어 있습니다.")

print(f"▶ '{collection_name}' 컬렉션 삭제 시작...")
deleted_count = delete_collection(collection_name)

if deleted_count == 0:
    print(f"▶ '{collection_name}' 컬렉션에 문서가 없거나 이미 비어 있습니다.")
else:
    print(f"✅ '{collection_name}' 컬렉션 문서 {deleted_count}개 삭제 완료.")
