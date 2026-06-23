# Firestore 매장 위치 저장 공통 (전량 삭제 후 재저장)

from firebase_admin import firestore

BATCH_SIZE = 400
DELETE_BATCH_SIZE = 400


def delete_collection(db, collection_name, batch_size=DELETE_BATCH_SIZE):
    collection_ref = db.collection(collection_name)
    total_deleted = 0

    while True:
        docs = list(collection_ref.limit(batch_size).stream())
        if not docs:
            break

        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        total_deleted += len(docs)
        print(f"  - {len(docs)}개 문서 삭제 (누적 {total_deleted}개)")

    if total_deleted:
        print(f"▶ {collection_name} 기존 {total_deleted}개 삭제 완료")
    else:
        print(f"▶ {collection_name} 컬렉션 비어 있음")
    return total_deleted


def save_stores_batch(db, stores, collection_name, batch_size=BATCH_SIZE):
    if not stores:
        return

    collection_ref = db.collection(collection_name)
    for start in range(0, len(stores), batch_size):
        chunk = stores[start:start + batch_size]
        batch = db.batch()
        for store in chunk:
            doc_id = str(store["shop_code"])
            batch.set(collection_ref.document(doc_id), store)
        batch.commit()
        print(f"✅ Firestore {collection_name} {len(chunk)}개 저장")


def flush_store_batches(db, stores, collection_name, batch_size=BATCH_SIZE):
    while len(stores) >= batch_size:
        save_stores_batch(db, stores[:batch_size], collection_name, batch_size)
        stores = stores[batch_size:]
    return stores
