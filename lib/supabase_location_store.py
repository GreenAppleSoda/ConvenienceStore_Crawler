# Supabase 매장 위치 저장 공통 모듈
# 테이블: store_locations (PK: store + shop_code), locations_meta

from datetime import datetime, timezone

from lib.supabase_store import get_supabase_client

BATCH_SIZE = 200
GEOHASH_PRECISION = 9
_GEOHASH_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def encode_geohash(latitude, longitude, precision=GEOHASH_PRECISION):
    lat_interval = [-90.0, 90.0]
    lon_interval = [-180.0, 180.0]
    geohash = []
    bits = [16, 8, 4, 2, 1]
    bit = 0
    ch = 0
    even = True

    while len(geohash) < precision:
        if even:
            mid = (lon_interval[0] + lon_interval[1]) / 2
            if longitude > mid:
                ch |= bits[bit]
                lon_interval[0] = mid
            else:
                lon_interval[1] = mid
        else:
            mid = (lat_interval[0] + lat_interval[1]) / 2
            if latitude > mid:
                ch |= bits[bit]
                lat_interval[0] = mid
            else:
                lat_interval[1] = mid

        even = not even
        if bit < 4:
            bit += 1
        else:
            geohash.append(_GEOHASH_BASE32[ch])
            bit = 0
            ch = 0

    return "".join(geohash)


def parse_coordinates(lat, lng):
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return None

    if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
        return None

    return lat_f, lng_f


def _stores_to_rows(stores):
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for store in stores:
        rows.append({
            "store": store["store"],
            "shop_code": str(store["shop_code"]),
            "name": store["name"],
            "address": store["address"],
            "phone": store.get("phone") or "",
            "lat": float(store["lat"]),
            "lng": float(store["lng"]),
            "geohash": store["geohash"],
            "services": store.get("services") or [],
            "updated_at": now,
        })
    return rows


def save_locations_batch(stores):
    if not stores:
        return

    client = get_supabase_client()
    rows = _stores_to_rows(stores)
    client.table("store_locations").upsert(
        rows,
        on_conflict="store,shop_code",
    ).execute()
    print(f"✅ Supabase store_locations {len(rows)}개 저장")


def flush_location_batches(stores):
    while len(stores) >= BATCH_SIZE:
        save_locations_batch(stores[:BATCH_SIZE])
        stores = stores[BATCH_SIZE:]
    return stores


def load_seen_shop_codes(store_brand):
    client = get_supabase_client()
    seen = set()
    page_size = 1000
    offset = 0

    while True:
        response = (
            client.table("store_locations")
            .select("shop_code")
            .eq("store", store_brand)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            break

        for row in rows:
            seen.add(str(row["shop_code"]))

        if len(rows) < page_size:
            break
        offset += page_size

    return seen


def delete_store_locations(store_brand):
    client = get_supabase_client()
    total_deleted = 0

    while True:
        response = (
            client.table("store_locations")
            .select("shop_code")
            .eq("store", store_brand)
            .limit(500)
            .execute()
        )
        rows = response.data or []
        if not rows:
            break

        shop_codes = [row["shop_code"] for row in rows]
        client.table("store_locations").delete().eq("store", store_brand).in_(
            "shop_code", shop_codes
        ).execute()
        total_deleted += len(shop_codes)

    if total_deleted:
        print(f"▶ Supabase store_locations/{store_brand} 기존 {total_deleted}개 삭제")
    return total_deleted


def _load_locations_meta_brands(client):
    response = (
        client.table("locations_meta")
        .select("brands")
        .eq("id", "current")
        .limit(1)
        .execute()
    )
    if not response or not response.data:
        return {}
    return dict(response.data[0].get("brands") or {})


def update_locations_meta(store_brand, store_count, meta_key=None):
    client = get_supabase_client()
    version = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc).isoformat()
    meta_key = meta_key or store_brand.replace("-", "_")

    brands = _load_locations_meta_brands(client)
    brands[meta_key] = {
        "version": version,
        "store_count": store_count,
        "updated_at": now,
    }
    client.table("locations_meta").upsert({
        "id": "current",
        "version": version,
        "brands": brands,
        "updated_at": now,
    }).execute()

    print(f"✅ Supabase locations_meta 갱신 ({meta_key}: {store_count}개)")
