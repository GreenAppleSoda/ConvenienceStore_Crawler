# GS25 매장 위치 크롤러 (Supabase)
# API: POST /gscvs/ko/store-services/locationList

import json
import time

import requests
from bs4 import BeautifulSoup

import lib._bootstrap  # noqa: F401
from lib.supabase_location_store import (
    encode_geohash,
    flush_location_batches,
    delete_store_locations,
    parse_coordinates,
    save_locations_batch,
    update_locations_meta,
)

BASE_URL = "https://gs25.gsretail.com"
LOCATIONS_URL = f"{BASE_URL}/gscvs/ko/store-services/locations"
SEARCH_URL = f"{BASE_URL}/gscvs/ko/store-services/locationList"

PAGE_SIZE = 5000
REQUEST_DELAY = 1
STORE_NAME = "GS25"

BASE_SEARCH_PAYLOAD = {
    "searchShopName": "",
    "searchSido": "",
    "searchGugun": "",
    "searchDong": "",
    "searchType": "",
    "searchTypeService": "0",
    "searchTypeToto": "0",
    "searchTypeCafe25": "0",
    "searchTypeInstant": "0",
    "searchTypeDrug": "0",
    "searchTypeSelf25": "0",
    "searchTypePost": "0",
    "searchTypeATM": "0",
    "searchTypeWithdrawal": "0",
    "searchTypeTaxrefund": "0",
    "searchTypeSmartAtm": "0",
    "searchTypeSelfCookingUtensils": "0",
    "searchTypeDeliveryService": "0",
    "searchTypeParcelService": "0",
    "searchTypePotatoes": "0",
    "searchTypeCardiacDefi": "0",
    "searchTypeFishShapedBun": "0",
    "searchTypeWine25": "0",
    "searchTypeGoPizza": "0",
    "searchTypeSpiritWine": "0",
    "searchTypeFreshGanghw": "0",
    "searchTypeMusinsa": "0",
    "searchTypePosa": "0",
}


def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
        "Referer": LOCATIONS_URL,
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    return session


def get_csrf_token(session):
    response = session.get(LOCATIONS_URL, timeout=15)
    response.raise_for_status()
    form = BeautifulSoup(response.text, "html.parser").find("form", id="CSRFForm")
    if not form or not form.find("input"):
        raise RuntimeError("CSRFToken을 찾을 수 없습니다.")
    return form.find("input")["value"]


def parse_api_response(text):
    body = json.loads(text)
    if isinstance(body, str):
        body = json.loads(body)
    return body


def fetch_location_page(session, csrf_token, page_num):
    payload = dict(BASE_SEARCH_PAYLOAD)
    payload["pageNum"] = str(page_num)
    payload["pageSize"] = str(PAGE_SIZE)

    response = session.post(
        f"{SEARCH_URL}?CSRFToken={csrf_token}",
        data=payload,
        timeout=30,
    )
    response.raise_for_status()
    return parse_api_response(response.text)


def parse_store(item):
    shop_code = str(item.get("shopCode", "")).strip()
    name = item.get("shopName", "").strip()
    address = item.get("address", "").strip()
    coords = parse_coordinates(item.get("longs"), item.get("lat"))

    if not shop_code or not name or not address or not coords:
        return None

    lat_f, lng_f = coords
    return {
        "store": STORE_NAME,
        "shop_code": shop_code,
        "name": name,
        "address": address,
        "phone": "",
        "lat": lat_f,
        "lng": lng_f,
        "geohash": encode_geohash(lat_f, lng_f),
        "services": item.get("offeringService") or [],
    }


def crawl_locations(session, csrf_token):
    stores = []
    page_num = 1
    total_pages = None

    while True:
        print(f"  - 전국 {page_num}페이지 요청...")
        data = fetch_location_page(session, csrf_token, page_num)

        if total_pages is None:
            pagination = data.get("pagination", {})
            total_pages = pagination.get("numberOfPages", 1)
            total_results = pagination.get("totalNumberOfResults", 0)
            print(f"  - 전국 총 {total_results}개 / {total_pages}페이지")

        for item in data.get("results", []):
            store = parse_store(item)
            if store:
                stores.append(store)

        if page_num >= total_pages:
            break

        page_num += 1
        if REQUEST_DELAY:
            time.sleep(REQUEST_DELAY)

    print(f"▶ GS25: {len(stores)}개 매장 추출 완료")
    return stores


delete_store_locations(STORE_NAME)

session = create_session()
csrf_token = get_csrf_token(session)

print("\n▶ GS25 전국 매장 크롤링 시작 (Supabase)...")
all_stores = crawl_locations(session, csrf_token)
pending_stores = flush_location_batches(all_stores)

if pending_stores:
    save_locations_batch(pending_stores)

update_locations_meta(STORE_NAME, len(all_stores))
print(f"\n✅ GS25 매장 Supabase 저장 완료. (총 {len(all_stores)}개)")
