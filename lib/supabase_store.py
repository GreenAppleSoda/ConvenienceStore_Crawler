# Supabase 저장 공통 모듈 (행사 상품 bulk snapshot)
# 프로젝트 루트의 .env:
#   SUPABASE_URL
#   SUPABASE_SERVICE_ROLE_KEY

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

from lib.paths import ENV_FILE

load_dotenv(ENV_FILE)

_client = None


def get_supabase_client():
    global _client
    if _client is not None:
        return _client

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL 과 SUPABASE_SERVICE_ROLE_KEY 가 필요합니다. "
            "프로젝트 루트에 .env 파일을 만들고 값을 설정하세요 (.env.example 참고)."
        )
    _client = create_client(url, key)
    return _client


def _load_meta_brands(client):
    response = (
        client.table("events_meta")
        .select("brands")
        .eq("id", "current")
        .limit(1)
        .execute()
    )
    if not response or not response.data:
        return {}
    return dict(response.data[0].get("brands") or {})


def save_event_snapshot(store, products, meta_key=None):
    client = get_supabase_client()
    version = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()
    meta_key = meta_key or store.replace("-", "_")

    snapshot = {
        "store": store,
        "version": version,
        "product_count": len(products),
        "products": products,
        "updated_at": now,
    }
    client.table("event_snapshots").upsert(snapshot).execute()

    brands = _load_meta_brands(client)
    brands[meta_key] = {
        "version": version,
        "product_count": len(products),
        "updated_at": now,
    }
    client.table("events_meta").upsert({
        "id": "current",
        "version": version,
        "brands": brands,
        "updated_at": now,
    }).execute()

    print(
        f"✅ Supabase event_snapshots/{store} 저장 완료 "
        f"({len(products)}개 상품, version={version})"
    )
