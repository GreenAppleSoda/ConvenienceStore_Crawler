# emart24 매장 위치 크롤러 (Supabase)
# API: GET /api1/store (전국 페이지네이션)

import math
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import runpy
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "ensure_project_root.py").is_file():
        runpy.run_path(str(_p / "ensure_project_root.py"), run_name="__main__")
        break
else:
    raise RuntimeError("ensure_project_root.py not found")
from lib.supabase_location_store import (
    delete_store_locations,
    encode_geohash,
    flush_location_batches,
    parse_coordinates,
    save_locations_batch,
    update_locations_meta,
)

BASE_URL = "https://emart24.co.kr"
STORE_URL = f"{BASE_URL}/api1/store"
STORE_REFERER = f"{BASE_URL}/store"

REQUEST_DELAY = 0.5
MAX_RETRIES = 5
RETRY_BACKOFF = 2
STORE_NAME = "emart24"

SERVICE_FLAGS = {
    "SVR_24": "24시간",
    "SVR_AUTO": "무인매장",
    "SVR_PARCEL": "택배",
    "SVR_ATM": "ATM",
    "SVR_WINE": "와인",
    "SVR_COFFEE": "커피",
    "SVR_SMOOTH": "스무디킹",
    "SVR_APPLE": "애플악세서리",
    "SVR_TOTO": "토토",
    "NBR_LICS_YN": "노브랜드",
}

BASE_STORE_PARAMS = {
    "search": "",
    "AREA1": "",
    "AREA2": "",
    "SVR_24": "",
    "SVR_AUTO": "",
    "SVR_PARCEL": "",
    "SVR_ATM": "",
    "SVR_WINE": "",
    "SVR_COFFEE": "",
    "SVR_SMOOTH": "",
    "SVR_APPLE": "",
    "SVR_TOTO": "",
    "NBR_LICS_YN": "",
    "USE_YN": "",
}


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
        "Referer": STORE_REFERER,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
    })
    return session


def parse_services(item):
    return [label for field, label in SERVICE_FLAGS.items() if item.get(field) == 1]


def parse_store(item):
    shop_code = str(item.get("CODE", "")).strip()
    name = (item.get("TITLE") or "").strip()
    address = (item.get("ADDRESS") or "").strip()
    coords = parse_coordinates(item.get("LATITUDE"), item.get("LONGITUDE"))

    if not shop_code or not name or not address or not coords:
        return None

    lat_f, lng_f = coords
    return {
        "store": STORE_NAME,
        "shop_code": shop_code,
        "name": name,
        "address": address,
        "phone": str(item.get("PHONE") or "").strip(),
        "lat": lat_f,
        "lng": lng_f,
        "geohash": encode_geohash(lat_f, lng_f),
        "services": parse_services(item),
    }


def fetch_store_page(session, page_num):
    params = dict(BASE_STORE_PARAMS)
    params["page"] = str(page_num)

    response = request_with_retry(
        session,
        "GET",
        STORE_URL,
        f"매장 {page_num}페이지",
        params=params,
        timeout=30,
    )
    body = response.json()
    if body.get("error") != 0:
        raise RuntimeError(f"API error: {body}")
    return body


def crawl_all_stores(session):
    pending_stores = []
    all_stores = []
    page_num = 1
    total_pages = None

    while True:
        print(f"  - {page_num}페이지 요청...")
        data = fetch_store_page(session, page_num)
        stores = data.get("data", [])

        if total_pages is None:
            total_count = data.get("count", 0)
            page_size = len(stores) or 40
            total_pages = max(1, math.ceil(total_count / page_size))
            print(f"  - 전국 총 {total_count}개 매장 / 약 {total_pages}페이지")

        if not stores:
            break

        for item in stores:
            store = parse_store(item)
            if store:
                all_stores.append(store)
                pending_stores.append(store)

        pending_stores = flush_location_batches(pending_stores)

        if total_pages and page_num >= total_pages:
            break

        page_num += 1
        if REQUEST_DELAY:
            time.sleep(REQUEST_DELAY)

    if pending_stores:
        save_locations_batch(pending_stores)

    return all_stores


delete_store_locations(STORE_NAME)

session = create_session()
print("\n▶ emart24 전국 매장 크롤링 시작 (Supabase)...")
all_stores = crawl_all_stores(session)

update_locations_meta(STORE_NAME, len(all_stores))
print(f"\n✅ emart24 매장 Supabase 저장 완료. (총 {len(all_stores)}개)")
