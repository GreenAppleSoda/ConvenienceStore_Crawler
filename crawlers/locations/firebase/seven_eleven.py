# 7-ELEVEN 매장 위치 크롤러
# API: storeLayerPop.asp + StoreGetGugun.asp
# 저장: 컬렉션 전량 삭제 후 재저장 (GS25 방식)

import hashlib
import re
import time

import requests
from bs4 import BeautifulSoup, NavigableString
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
from firebase_admin import firestore
from lib.firebase_client import get_firestore_client
from lib.firestore_location_store import (
    delete_collection,
    flush_store_batches,
    save_stores_batch,
)
from lib.supabase_location_store import encode_geohash, parse_coordinates

BASE_URL = "https://www.7-eleven.co.kr"
LAYER_POP_URL = f"{BASE_URL}/util/storeLayerPop.asp"
GUGUN_URL = f"{BASE_URL}/library/asp/StoreGetGugun.asp"

REQUEST_DELAY = 1
MAX_RETRIES = 5
RETRY_BACKOFF = 2
COLLECTION_NAME = "7-ELEVEN_locations"
STORE_NAME = "7-ELEVEN"

_MARKER_RE = re.compile(r"markerClick\([^,]+,([^,]+),([^)]+)\)")

SERVICE_ICON_LABELS = {
    "ico_24h.png": "24시간",
    "ico_cafe.png": "세븐카페",
    "ico_decaf.png": "디카페인",
    "ico_chicken.png": "치킨",
    "ico_potato2.png": "고구마·붕어빵",
    "ico_bakery.png": "베이커리",
    "ico_medical.png": "의약품",
    "ico_toto.png": "토토",
    "ico_basket.png": "당일픽업",
    "ico_reserve.png": "사전예약",
    "ico_signiture.png": "무인점포",
    "ico_parcel.png": "택배접수",
    "ico_locker.png": "무인 락커",
    "ico_atm.png": "ATM",
    "ico_fedex.png": "FedEx",
    "ico_cd.png": "CD",
    "ico_smartpick.png": "스마트픽",
    "ico_softcon.png": "소프트아이스크림",
    "ico_aed.png": "자동심장충격기(AED)",
    "ico_beadcon.png": "구슬아이스크림",
}

SERVICE_ALT_LABELS = {
    "카페": "세븐카페",
    "예약주문": "사전예약",
    "무인택배접수": "택배접수",
    "시디": "CD",
}

db = get_firestore_client()


def make_shop_code(name, lat, lng):
    raw = f"{name}|{lat:.6f}|{lng:.6f}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


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
        "Referer": f"{BASE_URL}/",
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "text/html, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    return session


def parse_name_from_span(span):
    if not span:
        return ""
    for child in span.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                return text
    return span.get_text(" ", strip=True)


def parse_services(anchor):
    services = []
    seen = set()
    for img in anchor.select("img"):
        src = img.get("src", "")
        filename = src.rsplit("/", 1)[-1]
        label = SERVICE_ICON_LABELS.get(filename)
        if not label:
            alt = (img.get("alt") or "").strip()
            label = SERVICE_ALT_LABELS.get(alt, alt) if alt else None
        if label and label not in seen:
            seen.add(label)
            services.append(label)
    return services


def parse_store_anchor(anchor):
    href = anchor.get("href", "")
    match = _MARKER_RE.search(href)
    if not match:
        return None

    coords = parse_coordinates(match.group(1), match.group(2))
    if not coords:
        return None

    lat_f, lng_f = coords
    spans = anchor.select("span")
    name = parse_name_from_span(spans[0]) if spans else ""
    address = spans[1].get_text(" ", strip=True).replace("\xa0", " ") if len(spans) > 1 else ""

    if not name or not address:
        return None

    return {
        "store": STORE_NAME,
        "shop_code": make_shop_code(name, lat_f, lng_f),
        "name": name,
        "address": address,
        "phone": "",
        "location": firestore.GeoPoint(lat_f, lng_f),
        "geohash": encode_geohash(lat_f, lng_f),
        "lat": lat_f,
        "lng": lng_f,
        "services": parse_services(anchor),
        "timestamp": firestore.SERVER_TIMESTAMP,
    }


def parse_sido_list(html):
    soup = BeautifulSoup(html, "html.parser")
    return [
        option.get("value", "").strip()
        for option in soup.select("#storeLaySido option")
        if option.get("value", "").strip()
    ]


def parse_gugun_list(html):
    soup = BeautifulSoup(html, "html.parser")
    return [
        option.get("value", "").strip()
        for option in soup.select("select option")
        if option.get("value", "").strip()
    ]


def parse_store_list(html):
    soup = BeautifulSoup(html, "html.parser")
    stores = []
    for anchor in soup.select("div.list_stroe:not(.type02) ul li a"):
        store = parse_store_anchor(anchor)
        if store:
            stores.append(store)
    return stores


def fetch_gugun_list(session, sido):
    response = request_with_retry(
        session,
        "POST",
        GUGUN_URL,
        f"{sido} 구군 목록",
        data={"Sido": sido, "selName": "storeLayGu"},
        timeout=30,
    )
    return parse_gugun_list(response.text)


def fetch_stores(session, sido, gugun):
    response = request_with_retry(
        session,
        "POST",
        LAYER_POP_URL,
        f"{sido} {gugun} 매장 목록",
        data={
            "storeLaySido": sido,
            "storeLayGu": gugun,
            "hiddentext": "none",
        },
        timeout=30,
    )
    return parse_store_list(response.text)


def crawl_all_stores(session):
    pending_stores = []
    all_stores = []

    init_response = request_with_retry(session, "GET", LAYER_POP_URL, "매장찾기 팝업", timeout=30)
    sido_list = parse_sido_list(init_response.text)
    print(f"▶ 시도 {len(sido_list)}개 확인")

    for sido in sido_list:
        print(f"\n▶ {sido} 구군 목록 로딩...")
        try:
            gugun_list = fetch_gugun_list(session, sido)
        except requests.RequestException as error:
            print(f"🚨 {sido} 구군 목록 실패, 다음 시도로 건너뜀: {error}")
            continue

        for gugun in gugun_list:
            print(f"  - {sido} {gugun} 매장 요청...")
            try:
                gugun_stores = fetch_stores(session, sido, gugun)
            except requests.RequestException as error:
                print(f"🚨 {sido} {gugun} 수집 실패, 다음 구군으로 건너뜀: {error}")
                pending_stores = flush_store_batches(db, pending_stores, COLLECTION_NAME)
                continue

            for store in gugun_stores:
                all_stores.append(store)
                pending_stores.append(store)

            pending_stores = flush_store_batches(db, pending_stores, COLLECTION_NAME)
            print(f"    → {len(gugun_stores)}개 조회")

            if REQUEST_DELAY:
                time.sleep(REQUEST_DELAY)

    if pending_stores:
        save_stores_batch(db, pending_stores, COLLECTION_NAME)

    return all_stores


delete_collection(db, COLLECTION_NAME)

session = create_session()
print("\n▶ 7-ELEVEN 전국 매장 크롤링 시작...")
all_stores = crawl_all_stores(session)
print(f"\n✅ 7-ELEVEN 매장 Firestore 저장 완료. (총 {len(all_stores)}개)")
