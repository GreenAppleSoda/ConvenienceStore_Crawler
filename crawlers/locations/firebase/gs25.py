# GS25 매장 위치 크롤러
# API: POST /gscvs/ko/store-services/locationList?CSRFToken=...
#   - searchSido / searchGugun / searchDong: 지역 코드 (빈 값 = 전국)
#   - searchType*: 서비스 필터 (0 = 필터 없음)
#   - pageNum / pageSize: 페이지네이션
#
# Firestore 저장 필드 (주변 매장 검색용):
#   - location: GeoPoint (위도, 경도)
#   - geohash: 반경 검색용 문자열 (GeoFirestore 등)
#   - lat / lng: 숫자형 좌표 (앱 표시·거리 계산 편의용)

import json
import time

import requests
from bs4 import BeautifulSoup
import lib._bootstrap  # noqa: F401
from lib.firebase_client import get_firestore_client
from lib.firestore_location_store import (
    delete_collection,
    flush_store_batches,
    save_stores_batch,
)
from firebase_admin import firestore

BASE_URL = "https://gs25.gsretail.com"
LOCATIONS_URL = f"{BASE_URL}/gscvs/ko/store-services/locations"
SEARCH_URL = f"{BASE_URL}/gscvs/ko/store-services/locationList"

PAGE_SIZE = 5000
REQUEST_DELAY = 1
GEOHASH_PRECISION = 9

_GEOHASH_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

# searchSido / searchGugun / searchDong 을 비우면 전국 조회
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

db = get_firestore_client()


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


def fetch_location_page(session, csrf_token, page_num, search_payload=None):
    payload = dict(BASE_SEARCH_PAYLOAD)
    if search_payload:
        payload.update(search_payload)
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
    # GS25 API 필드명이 반대: longs=위도, lat=경도
    coords = parse_coordinates(item.get("longs"), item.get("lat"))

    if not shop_code or not name or not address or not coords:
        return None

    lat_f, lng_f = coords

    return {
        "store": "GS25",
        "shop_code": shop_code,
        "name": name,
        "address": address,
        "location": firestore.GeoPoint(lat_f, lng_f),
        "geohash": encode_geohash(lat_f, lng_f),
        "lat": lat_f,
        "lng": lng_f,
        "services": item.get("offeringService") or [],
        "timestamp": firestore.SERVER_TIMESTAMP,
    }


def crawl_locations(session, csrf_token, search_payload=None, label="전국"):
    stores = []
    page_num = 1
    total_pages = None

    while True:
        print(f"  - {label} {page_num}페이지 요청...")
        data = fetch_location_page(session, csrf_token, page_num, search_payload)

        if total_pages is None:
            pagination = data.get("pagination", {})
            total_pages = pagination.get("numberOfPages", 1)
            total_results = pagination.get("totalNumberOfResults", 0)
            print(f"  - {label} 총 {total_results}개 / {total_pages}페이지")

        page_items = data.get("results", [])
        if not page_items:
            break

        for item in page_items:
            store = parse_store(item)
            if store:
                stores.append(store)

        if page_num >= total_pages:
            break

        page_num += 1
        if REQUEST_DELAY:
            time.sleep(REQUEST_DELAY)

    print(f"▶ {label}: {len(stores)}개 매장 추출 완료")
    return stores


collection_name = "GS25_locations"
delete_collection(db, collection_name)

session = create_session()
csrf_token = get_csrf_token(session)

print("\n▶ GS25 전국 매장 크롤링 시작...")
all_stores = crawl_locations(session, csrf_token)
pending_stores = flush_store_batches(db, all_stores, collection_name)

if pending_stores:
    save_stores_batch(db, pending_stores, collection_name)

print(f"\n✅ GS25 매장 Firestore 저장 완료. (총 {len(all_stores)}개)")
