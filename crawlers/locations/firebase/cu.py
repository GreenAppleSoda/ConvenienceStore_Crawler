# CU 매장 위치 크롤러
# API: POST https://www.pocketcu.co.kr/api/store/search/list
# 저장: 컬렉션 전량 삭제 후 재저장 (GS25 방식)

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import lib._bootstrap  # noqa: F401
from firebase_admin import firestore
from lib.firebase_client import get_firestore_client
from lib.firestore_location_store import (
    delete_collection,
    flush_store_batches,
    save_stores_batch,
)
from lib.supabase_location_store import encode_geohash, parse_coordinates

POCKETCU_URL = "https://www.pocketcu.co.kr/api/store/search/list"

REQUEST_DELAY = 0.5
MAX_RETRIES = 5
RETRY_BACKOFF = 2
COLLECTION_NAME = "CU_locations"

SERVICE_FLAGS = {
    "hour24Yn": "24시간",
    "jumpoDelivYn": "택배 서비스",
    "bakeryYn": "베이커리 판매",
    "friedYn": "튀김 판매",
    "coffeeYn": "에스프레소 커피 판매",
    "lottoYn": "로또 판매",
    "totoYn": "스포츠토토",
    "atmYn": "현금지급기",
    "jumpoMultiDeviceYn": "무인복합기",
    "jumpoPosCashYn": "POS현금인출",
    "jumpoBatteryYn": "공유보조 배터리",
}

db = get_firestore_client()


def request_with_retry(session, method, url, label, **kwargs):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt >= MAX_RETRIES:
                break
            wait = RETRY_BACKOFF ** attempt
            print(f"⚠️ {label} 요청 실패 ({attempt}/{MAX_RETRIES}): {error}")
            print(f"   {wait}초 후 재시도...")
            time.sleep(wait)
    raise last_error


def create_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    return session


def build_address(item):
    addr_fst = (item.get("addrFst") or "").strip()
    addr_detail = (item.get("addrDetail") or "").strip()
    if addr_fst and addr_detail:
        return f"{addr_fst} {addr_detail}"
    return addr_fst or addr_detail


def parse_services(item):
    return [label for field, label in SERVICE_FLAGS.items() if item.get(field) == "Y"]


def parse_store(item):
    shop_code = str(item.get("storeCd", "")).strip()
    name = (item.get("storeNm") or "").strip()
    address = build_address(item)
    coords = parse_coordinates(item.get("latVal"), item.get("longVal"))

    if not shop_code or not name or not address or not coords:
        return None

    lat_f, lng_f = coords
    return {
        "store": "CU",
        "shop_code": shop_code,
        "name": name,
        "address": address,
        "phone": (item.get("storeTelNo") or "").strip(),
        "location": firestore.GeoPoint(lat_f, lng_f),
        "geohash": encode_geohash(lat_f, lng_f),
        "lat": lat_f,
        "lng": lng_f,
        "services": parse_services(item),
        "timestamp": firestore.SERVER_TIMESTAMP,
    }


def fetch_store_page(session, page_index):
    response = request_with_retry(
        session,
        "POST",
        POCKETCU_URL,
        f"pocketcu {page_index}페이지",
        json={"firstRowNum": str(page_index), "searchWord": ""},
        timeout=30,
    )
    return response.json()


def crawl_all_stores(session):
    pending_stores = []
    all_stores = []
    page_index = 0

    while True:
        print(f"  - {page_index}페이지 요청...")
        data = fetch_store_page(session, page_index)
        stores = data.get("storeList", [])

        if page_index == 0:
            print(f"  - 전국 총 {data.get('storeCnt', 0)}개 매장")

        if not stores:
            break

        for item in stores:
            store = parse_store(item)
            if store:
                all_stores.append(store)
                pending_stores.append(store)

        pending_stores = flush_store_batches(db, pending_stores, COLLECTION_NAME)

        page_index += 1
        if REQUEST_DELAY:
            time.sleep(REQUEST_DELAY)

    if pending_stores:
        save_stores_batch(db, pending_stores, COLLECTION_NAME)

    return all_stores


delete_collection(db, COLLECTION_NAME)

session = create_session()
print("\n▶ CU 전국 매장 크롤링 시작 (pocketcu API)...")
all_stores = crawl_all_stores(session)
print(f"\n✅ CU 매장 Firestore 저장 완료. (총 {len(all_stores)}개)")
