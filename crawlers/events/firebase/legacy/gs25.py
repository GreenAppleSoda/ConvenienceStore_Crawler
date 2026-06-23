# GS25_crawler.py 수정본
# 수정 사항:
#   - Selenium → event-goods-search JSON API 방식으로 전환
#   - 단일 페이지 탭 중복 저장 버그 제거 (페이지 번호 기반 수집)
#   - 탭별 크롤링 직후 배치 저장

import json

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

BATCH_SIZE = 400
PAGE_SIZE = 8

db = get_firestore_client()


def get_all_docs_in_batches(collection_name, batch_size=50):
    docs = []
    query = db.collection(collection_name).order_by("__name__").limit(batch_size)
    while True:
        batch_list = list(query.stream())
        if not batch_list:
            break
        docs.extend(batch_list)
        query = (
            db.collection(collection_name)
            .order_by("__name__")
            .start_after(batch_list[-1])
            .limit(batch_size)
        )
    return docs


def save_products_to_firestore_batch(data_list, collection_name):
    if not data_list:
        return

    batch = db.batch()
    collection_ref = db.collection(collection_name)
    for data in data_list:
        batch.set(collection_ref.document(), data)
    batch.commit()
    print(f"✅ Firestore에 {len(data_list)}개 문서 배치 저장 완료!")


def flush_batches(products, collection_name):
    while len(products) >= BATCH_SIZE:
        save_products_to_firestore_batch(products[:BATCH_SIZE], collection_name)
        products = products[BATCH_SIZE:]
    return products


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
        "store": "GS25",
        "event_type": event_type,
        "name": name,
        "price": format_price(price),
        "image_url": image_url,
        "timestamp": firestore.SERVER_TIMESTAMP,
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


collection_name = "GS25_events"
docs = get_all_docs_in_batches(collection_name, batch_size=50)
for doc in docs:
    doc.reference.delete()

print(f"{collection_name} 컬렉션 초기화 완료!")

session = create_session()
csrf_token = get_csrf_token(session)
pending_products = []

for parameter_list, tab_label in EVENT_TABS:
    print(f"\n▶ {tab_label} 탭 크롤링 시작...")
    tab_products = crawl_tab(session, csrf_token, parameter_list, tab_label)
    pending_products.extend(tab_products)
    pending_products = flush_batches(pending_products, collection_name)

if pending_products:
    save_products_to_firestore_batch(pending_products, collection_name)

print("\n✅ 모든 크롤링 및 Firestore 저장 작업 완료.")
