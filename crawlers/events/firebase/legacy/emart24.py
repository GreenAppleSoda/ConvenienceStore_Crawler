# emart24_crawler.py 수정본
# 수정 사항:
#   - 행사 카테고리별 URL 분리 (category_seq: 1=1+1, 2=2+1, 3=3+1, 4=세일, 12=골라담기)
#   - 카테고리별 페이지네이션 + 탭별 배치 저장
#   - 루프 종료 후 잔여 데이터 flush

import logging

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

logging.basicConfig(
    filename="emart24_crawler_fixed.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

BASE_URL = (
    "https://emart24.co.kr/goods/event"
    "?search=&page={page}&category_seq={category_seq}&base_category_seq=&align="
)

# (category_seq, Firestore event_type)
EVENT_CATEGORIES = [
    (1, "1+1"),
    (2, "2+1"),
    (3, "3+1"),
    (4, "할인"),      # 세일 탭 (다른 편의점과 통일)
    (12, "골라담기"),
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
    logging.info(f"✅ Firestore에 {len(data_list)}개 문서 배치 저장 완료!")


def flush_batches(products, collection_name):
    while len(products) >= BATCH_SIZE:
        save_products_to_firestore_batch(products[:BATCH_SIZE], collection_name)
        products = products[BATCH_SIZE:]
    return products


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
        "store": "emart24",
        "event_type": event_type,
        "name": name,
        "price": price,
        "image_url": img_url,
        "timestamp": firestore.SERVER_TIMESTAMP,
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
        logging.info(f"  - {event_type} {page}페이지 크롤링 중... ({url})")

        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"🚨 요청 오류 ({event_type} p{page}): {e}")
            logging.error(f"🚨 요청 오류 ({event_type} p{page}): {e}")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        items = soup.select("div.itemWrap")

        if not items:
            print(f"  - {event_type}: 상품 없음 (페이지 {page})")
            logging.info(f"  - {event_type}: 상품 없음 (페이지 {page})")
            break

        for item in items:
            product = parse_product(item, event_type)
            if product:
                products.append(product)
                print(f"[{event_type}] {product['name']} - {product['price']} (추출 완료)")
                logging.info(f"[{event_type}] {product['name']} - {product['price']} (추출 완료)")

        if not has_next_page(soup):
            break
        page += 1

    print(f"▶ {event_type} 카테고리: {len(products)}개 상품 추출 완료")
    logging.info(f"▶ {event_type} 카테고리: {len(products)}개 상품 추출 완료")
    return products


collection_name = "emart24_events"
docs = get_all_docs_in_batches(collection_name, batch_size=50)
for doc in docs:
    doc.reference.delete()

print(f"{collection_name} 컬렉션 초기화 완료!")
logging.info(f"{collection_name} 컬렉션 초기화 완료!")

session = create_session()
pending_products = []

for category_seq, event_type in EVENT_CATEGORIES:
    print(f"\n▶ {event_type} (category_seq={category_seq}) 크롤링 시작...")
    category_products = crawl_category(session, category_seq, event_type)
    pending_products.extend(category_products)
    pending_products = flush_batches(pending_products, collection_name)

if pending_products:
    save_products_to_firestore_batch(pending_products, collection_name)

print("\n✅ 크롤링 작업 완료.")
logging.info("✅ 크롤링 작업 완료.")
