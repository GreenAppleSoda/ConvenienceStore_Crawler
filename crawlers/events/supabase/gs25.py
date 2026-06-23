# GS25 행사 상품 크롤러 (Supabase 백업)
# Firestore bulk document와 동일한 products 구조를 Supabase event_snapshots에 저장

import json

import requests
from bs4 import BeautifulSoup

import lib._bootstrap  # noqa: F401
from lib.supabase_store import save_event_snapshot

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


session = create_session()
csrf_token = get_csrf_token(session)
all_products = []

for parameter_list, tab_label in EVENT_TABS:
    print(f"\n▶ {tab_label} 탭 크롤링 시작...")
    all_products.extend(crawl_tab(session, csrf_token, parameter_list, tab_label))

if not all_products:
    raise RuntimeError("저장할 상품이 없습니다.")

save_event_snapshot(STORE_NAME, all_products)
print("\n✅ GS25 Supabase 크롤링 및 저장 작업 완료.")
