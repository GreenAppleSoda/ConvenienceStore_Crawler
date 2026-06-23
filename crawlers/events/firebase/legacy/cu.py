# CU_crawler.py 수정본
# 수정 사항:
#   - Selenium → plusAjax.do HTML API 방식으로 전환
#   - 건별 .add() → 배치 저장 + 잔여 flush
#   - searchCondition: 23=1+1, 24=2+1 (탭별 전체 페이지 수집)

import requests
from bs4 import BeautifulSoup
import lib._bootstrap  # noqa: F401
from lib.firebase_client import get_firestore_client
from firebase_admin import firestore

PLUS_URL = "https://cu.bgfretail.com/event/plus.do?category=event&depth2=1&sf=N"
API_URL = "https://cu.bgfretail.com/event/plusAjax.do"

# searchCondition 값 (1+1 탭 cURL 기준 23, 2+1은 API 확인값)
EVENT_TABS = [
    ("23", "1+1"),
    ("24", "2+1"),
]

BATCH_SIZE = 400

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
        "Referer": PLUS_URL,
        "Origin": "https://cu.bgfretail.com",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "text/html, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    return session


def fetch_plus_page(session, search_condition, page_index, list_type):
    response = session.post(
        API_URL,
        data={
            "pageIndex": str(page_index),
            "listType": str(list_type),
            "searchCondition": search_condition,
            "user_id": "",
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.text


def parse_product(product_el):
    name_tag = product_el.find("div", class_="name")
    product_name = name_tag.p.text.strip() if name_tag and name_tag.p else None

    price_tag = product_el.find("div", class_="price")
    product_price = price_tag.strong.text.strip() if price_tag and price_tag.strong else None

    img_tag = product_el.find("div", class_="prod_img")
    img_url = None
    if img_tag and img_tag.img and img_tag.img.get("src"):
        src = img_tag.img["src"]
        img_url = src if src.startswith("http") else "https:" + src

    event_tag = product_el.find("div", class_="badge")
    event_type = event_tag.span.text.strip() if event_tag and event_tag.span else None

    if not product_name or not product_price or not img_url or not event_type:
        return None

    return {
        "store": "CU",
        "event_type": event_type,
        "name": product_name,
        "price": product_price,
        "image_url": img_url,
        "timestamp": firestore.SERVER_TIMESTAMP,
    }


def crawl_event_tab(session, search_condition, tab_label):
    products = []
    page_index = 1

    while True:
        list_type = 0 if page_index == 1 else 1
        print(f"  - {tab_label} {page_index}페이지 요청 (searchCondition={search_condition})...")
        html = fetch_plus_page(session, search_condition, page_index, list_type)
        soup = BeautifulSoup(html, "html.parser")
        items = soup.find_all("li", class_="prod_list")

        for item in items:
            product = parse_product(item)
            if product:
                products.append(product)

        has_more = bool(soup.find(class_="prodListBtn-w"))
        print(f"  - {tab_label} {page_index}페이지: {len(items)}개, 더보기={has_more}")

        if not has_more:
            break
        page_index += 1

    print(f"▶ {tab_label} 탭: {len(products)}개 상품 추출 완료")
    return products


collection_name = "CU_events"
docs = get_all_docs_in_batches(collection_name, batch_size=50)
for doc in docs:
    doc.reference.delete()

print(f"{collection_name} 컬렉션 초기화 완료!")

session = create_session()
session.get(PLUS_URL, timeout=15)

pending_products = []

for search_condition, tab_label in EVENT_TABS:
    print(f"\n▶ {tab_label} 탭 크롤링 시작...")
    tab_products = crawl_event_tab(session, search_condition, tab_label)
    pending_products.extend(tab_products)
    pending_products = flush_batches(pending_products, collection_name)

if pending_products:
    save_products_to_firestore_batch(pending_products, collection_name)

print("\n✅ 모든 크롤링 및 Firestore 저장 작업 완료.")
