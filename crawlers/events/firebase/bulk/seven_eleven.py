# 7-ELEVEN 행사 상품 크롤러 (bulk document)
# 브랜드 전체 상품을 7-ELEVEN_events/current 문서 1개에 저장 (read 절감용)
# GitHub Actions에서는 해외 IP 차단으로 실패할 수 있음 → 로컬 실행 권장

from datetime import datetime, timezone

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

EVENT_TABS = [
    (1, "1+1"),
    (2, "2+1"),
    (3, "덤 증정"),
    (4, "할인"),
]

STORE_NAME = "7-ELEVEN"
COLLECTION_NAME = "7-ELEVEN_events"
DOCUMENT_ID = "current"
META_COLLECTION = "events_meta"
META_DOCUMENT_ID = "current"
META_KEY = "7_ELEVEN"

db = get_firestore_client()


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
        "store": STORE_NAME,
        "event_type": event_type,
        "name": name,
        "price": price,
        "image_url": image_url,
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

    db.collection(META_COLLECTION).document(META_DOCUMENT_ID).set({
        "version": version,
        f"{META_KEY}_version": version,
        f"{META_KEY}_product_count": len(products),
        f"{META_KEY}_updated_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)

    print(f"✅ {COLLECTION_NAME}/{DOCUMENT_ID} 저장 완료 ({len(products)}개 상품, version={version})")


all_products = []

for p_tab, event_type in EVENT_TABS:
    print(f"\n▶ {event_type} 탭 크롤링 시작...")
    all_products.extend(crawl_tab(p_tab, event_type))

if not all_products:
    raise RuntimeError("저장할 상품이 없습니다.")

save_bulk_document(all_products)
print("\n✅ 7-ELEVEN bulk document 크롤링 및 Firestore 저장 작업 완료.")
