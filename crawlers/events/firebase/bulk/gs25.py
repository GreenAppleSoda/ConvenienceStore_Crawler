# GS25 행사 상품 크롤러 (bulk document)
# 브랜드 전체 상품을 GS25_events/current 문서 1개에 저장 (read 절감용)
# 상품 필드는 기존과 동일, 문서 단위로 version / updated_at / product_count 포함

import json
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
import lib._bootstrap  # noqa: F401
from lib.firebase_client import get_firestore_client
from firebase_admin import firestore

BASE_URL = "http://gs25.gsretail.com"
PAGE_URL = f"{BASE_URL}/gscvs/ko/products/event-goods"
SEARCH_URL = f"{BASE_URL}/gscvs/ko/products/event-goods-search"

EVENT_TABS = [
    ("ONE_TO_ONE", "1+1"),
    ("TWO_TO_ONE", "2+1"),
    ("GIFT", "덤 증정"),
]

PAGE_SIZE = 8
STORE_NAME = "GS25"
COLLECTION_NAME = "GS25_events"
DOCUMENT_ID = "current"
META_COLLECTION = "events_meta"
META_DOCUMENT_ID = "current"

db = get_firestore_client()


def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
        "Referer": PAGE_URL,
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    })
    return session


def get_csrf_token(session):
    response = session.get(PAGE_URL, timeout=15)
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


def fetch_event_goods_page(session, csrf_token, parameter_list, page_num):
    response = session.post(
        f"{SEARCH_URL}?CSRFToken={csrf_token}",
        data={
            "pageNum": str(page_num),
            "pageSize": str(PAGE_SIZE),
            "searchType": "",
            "searchWord": "",
            "parameterList": parameter_list,
        },
        timeout=15,
    )
    response.raise_for_status()
    return parse_api_response(response.text)


def format_price(price):
    return f"{int(price):,}"


def parse_product(item):
    image_url = item.get("attFileNm", "")
    if not image_url or "null" in image_url:
        return None

    name = item.get("goodsNm", "").strip()
    price = item.get("price")
    event_type = item.get("eventTypeNm", "").strip()

    if not name or price is None or not event_type:
        return None

    return {
        "store": STORE_NAME,
        "event_type": event_type,
        "name": name,
        "price": format_price(price),
        "image_url": image_url,
    }


def crawl_tab(session, csrf_token, parameter_list, tab_label):
    products = []
    page_num = 1
    total_pages = None

    while True:
        print(f"  - {tab_label} {page_num}페이지 요청...")
        data = fetch_event_goods_page(session, csrf_token, parameter_list, page_num)

        if total_pages is None:
            total_pages = data["pagination"]["numberOfPages"]
            print(f"  - {tab_label} 총 {data['pagination']['totalNumberOfResults']}개 / {total_pages}페이지")

        for item in data.get("results", []):
            product = parse_product(item)
            if product:
                products.append(product)

        if page_num >= total_pages:
            break
        page_num += 1

    print(f"▶ {tab_label} 탭: {len(products)}개 상품 추출 완료")
    return products


def save_bulk_document(products):
    version = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bulk_doc = {
        "store": STORE_NAME,
        "version": version,
        "product_count": len(products),
        "products": products,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    db.collection(COLLECTION_NAME).document(DOCUMENT_ID).set(bulk_doc)

    meta_key = STORE_NAME.replace("-", "_")
    db.collection(META_COLLECTION).document(META_DOCUMENT_ID).set({
        "version": version,
        f"{meta_key}_version": version,
        f"{meta_key}_product_count": len(products),
        f"{meta_key}_updated_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)

    print(f"✅ {COLLECTION_NAME}/{DOCUMENT_ID} 저장 완료 ({len(products)}개 상품, version={version})")


session = create_session()
csrf_token = get_csrf_token(session)
all_products = []

for parameter_list, tab_label in EVENT_TABS:
    print(f"\n▶ {tab_label} 탭 크롤링 시작...")
    all_products.extend(crawl_tab(session, csrf_token, parameter_list, tab_label))

if not all_products:
    raise RuntimeError("저장할 상품이 없습니다.")

save_bulk_document(all_products)
print("\n✅ GS25 bulk document 크롤링 및 Firestore 저장 작업 완료.")
