# emart24 행사 상품 크롤러 (bulk document)
# 브랜드 전체 상품을 emart24_events/current 문서 1개에 저장 (read 절감용)

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
from requests.adapters import HTTPAdapter, Retry

BASE_URL = (
    "https://emart24.co.kr/goods/event"
    "?search=&page={page}&category_seq={category_seq}&base_category_seq=&align="
)

EVENT_CATEGORIES = [
    (1, "1+1"),
    (2, "2+1"),
    (3, "3+1"),
    (4, "할인"),
    (12, "골라담기"),
]

STORE_NAME = "emart24"
COLLECTION_NAME = "emart24_events"
DOCUMENT_ID = "current"
META_COLLECTION = "events_meta"
META_DOCUMENT_ID = "current"

db = get_firestore_client()


def create_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
    })
    return session


def parse_product(item, event_type):
    img_tag = item.select_one("div.itemSpImg img")
    img_url = img_tag["src"] if img_tag and img_tag.get("src") else None

    name_tag = item.select_one("div.itemtitle a")
    name = name_tag.text.strip() if name_tag else None

    price_tag = item.select_one("a.price")
    price = price_tag.text.strip() if price_tag else None

    if not name or not price or not img_url:
        return None

    return {
        "store": STORE_NAME,
        "event_type": event_type,
        "name": name,
        "price": price,
        "image_url": img_url,
    }


def has_next_page(soup):
    next_div = soup.select_one("div.next")
    if not next_div:
        return False
    return "opacity: 0.3" not in next_div.get("style", "")


def crawl_category(session, category_seq, event_type):
    products = []
    page = 1

    while True:
        url = BASE_URL.format(page=page, category_seq=category_seq)
        print(f"  - {event_type} {page}페이지 크롤링 중...")

        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
        except requests.exceptions.RequestException as error:
            print(f"🚨 요청 오류 ({event_type} p{page}): {error}")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        items = soup.select("div.itemWrap")

        if not items:
            print(f"  - {event_type}: 상품 없음 (페이지 {page})")
            break

        for item in items:
            product = parse_product(item, event_type)
            if product:
                products.append(product)

        if not has_next_page(soup):
            break
        page += 1

    print(f"▶ {event_type} 카테고리: {len(products)}개 상품 추출 완료")
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
        f"{STORE_NAME}_version": version,
        f"{STORE_NAME}_product_count": len(products),
        f"{STORE_NAME}_updated_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)

    print(f"✅ {COLLECTION_NAME}/{DOCUMENT_ID} 저장 완료 ({len(products)}개 상품, version={version})")


session = create_session()
all_products = []

for category_seq, event_type in EVENT_CATEGORIES:
    print(f"\n▶ {event_type} (category_seq={category_seq}) 크롤링 시작...")
    all_products.extend(crawl_category(session, category_seq, event_type))

if not all_products:
    raise RuntimeError("저장할 상품이 없습니다.")

save_bulk_document(all_products)
print("\n✅ emart24 bulk document 크롤링 및 Firestore 저장 작업 완료.")
