# 7-ELEVEN_crawler.py 수정본
# 수정 사항:
#   - Selenium → AJAX API (listMoreAjax.asp) 방식으로 전환
#     (할인 탭 등 대량 상품에서 Chrome 세션 종료 문제 해결)
#   - 태그 없는 상품도 저장
#   - 탭별 크롤링 직후 배치 저장 (중간 실패 시에도 완료된 탭 데이터 보존)
#   - seven11_common 의존 제거 (API/파싱 로직 인라인)

import requests
from bs4 import BeautifulSoup
import runpy
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "ensure_project_root.py").is_file():
        runpy.run_path(str(_p / "ensure_project_root.py"), run_name="__main__")
        break
else:
    raise RuntimeError("ensure_project_root.py not found")
from lib.firebase_client import get_firestore_client
from firebase_admin import firestore

DOMAIN = "https://www.7-eleven.co.kr"
LIST_MORE_URL = f"{DOMAIN}/product/listMoreAjax.asp"
FIRST_PAGE_SIZE = 13
NEXT_PAGE_SIZE = 10

# pTab: 1=1+1, 2=2+1, 3=덤 증정, 4=할인
EVENT_TABS = [
    (1, "1+1"),
    (2, "2+1"),
    (3, "덤 증정"),
    (4, "할인"),
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


def fetch_event_page(p_tab, page_size, page_number):
    response = requests.post(
        LIST_MORE_URL,
        data={
            "intCurrPage": page_number,
            "intPageSize": page_size,
            "pTab": p_tab,
        },
        timeout=15,
    )
    if response.ok:
        return response.text
    return None


def parse_item_list(html_text):
    if not html_text:
        return []
    soup = BeautifulSoup(html_text, "html.parser")
    items = soup.findChildren("li", recursive=False)
    return items[:-1] if items else []


def parse_product(item, event_type):
    name_el = item.find("div", class_="name") or item.find("dd", class_="txt_product")
    price_el = item.find("div", class_="price") or item.find("dd", class_="price_list")
    img_el = item.find("img")

    if not name_el or not price_el or not img_el or not img_el.get("src"):
        return None

    name = name_el.get_text(strip=True)
    price = price_el.get_text(strip=True).replace("\n", "")
    src = img_el["src"]
    image_url = f"{DOMAIN}{src}" if src.startswith("/") else src

    return {
        "store": "7-ELEVEN",
        "event_type": event_type,
        "name": name,
        "price": price,
        "image_url": image_url,
        "timestamp": firestore.SERVER_TIMESTAMP,
    }


def crawl_tab(p_tab, event_type):
    products = []
    page_number = 1

    page1_data = fetch_event_page(p_tab, FIRST_PAGE_SIZE, page_number)
    if not page1_data:
        print(f"⚠️ {event_type} 탭 1페이지 로드 실패")
        return products

    for item in parse_item_list(page1_data):
        product = parse_product(item, event_type)
        if product:
            products.append(product)

    while True:
        page_number += 1
        page_data = fetch_event_page(p_tab, NEXT_PAGE_SIZE, page_number)
        if not page_data:
            print(f"⚠️ {event_type} 탭 {page_number}페이지 요청 실패")
            break

        page_items = parse_item_list(page_data)
        if not page_items:
            break

        for item in page_items:
            product = parse_product(item, event_type)
            if product:
                products.append(product)

    print(f"▶ {event_type} 탭: {len(products)}개 상품 추출 완료")
    return products


collection_name = "7-ELEVEN_events"
docs = get_all_docs_in_batches(collection_name, batch_size=50)
for doc in docs:
    doc.reference.delete()

print(f"{collection_name} 컬렉션 초기화 완료!")

pending_products = []

for p_tab, event_type in EVENT_TABS:
    print(f"\n▶ {event_type} 탭 크롤링 시작...")
    tab_products = crawl_tab(p_tab, event_type)
    pending_products.extend(tab_products)
    pending_products = flush_batches(pending_products, collection_name)

if pending_products:
    save_products_to_firestore_batch(pending_products, collection_name)

print("\n✅ 모든 크롤링 및 Firestore 저장 작업 완료.")
