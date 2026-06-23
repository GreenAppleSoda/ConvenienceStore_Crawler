# CU 행사 상품 크롤러 (Supabase 백업)

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
from lib.supabase_store import save_event_snapshot

PLUS_URL = "https://cu.bgfretail.com/event/plus.do?category=event&depth2=1&sf=N"
API_URL = "https://cu.bgfretail.com/event/plusAjax.do"

EVENT_TABS = [
    ("23", "1+1"),
    ("24", "2+1"),
]

STORE_NAME = "CU"


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
        "store": STORE_NAME,
        "event_type": event_type,
        "name": product_name,
        "price": product_price,
        "image_url": img_url,
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


session = create_session()
session.get(PLUS_URL, timeout=15)
all_products = []

for search_condition, tab_label in EVENT_TABS:
    print(f"\n▶ {tab_label} 탭 크롤링 시작...")
    all_products.extend(crawl_event_tab(session, search_condition, tab_label))

if not all_products:
    raise RuntimeError("저장할 상품이 없습니다.")

save_event_snapshot(STORE_NAME, all_products)
print("\n✅ CU Supabase 크롤링 및 저장 작업 완료.")
