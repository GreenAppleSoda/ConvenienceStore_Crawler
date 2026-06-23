# 7-ELEVEN 행사 상품 크롤러 (Supabase 백업)

from bs4 import BeautifulSoup
import runpy
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "ensure_project_root.py").is_file():
        runpy.run_path(str(_p / "ensure_project_root.py"), run_name="__main__")
        break
else:
    raise RuntimeError("ensure_project_root.py not found")
from lib.seven_eleven_http import BASE_URL, create_session, request_with_retry, warm_up_session
from lib.supabase_store import save_event_snapshot

LIST_MORE_URL = f"{BASE_URL}/product/listMoreAjax.asp"
FIRST_PAGE_SIZE = 13
NEXT_PAGE_SIZE = 10

EVENT_TABS = [
    (1, "1+1"),
    (2, "2+1"),
    (3, "덤 증정"),
    (4, "할인"),
]

STORE_NAME = "7-ELEVEN"
META_KEY = "7_ELEVEN"

session = create_session()
warm_up_session(session)


def fetch_event_page(p_tab, page_size, page_number):
    response = request_with_retry(
        session,
        "POST",
        LIST_MORE_URL,
        f"행사 목록 pTab={p_tab} page={page_number}",
        data={
            "intCurrPage": page_number,
            "intPageSize": page_size,
            "pTab": p_tab,
        },
    )
    return response.text


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
    image_url = f"{BASE_URL}{src}" if src.startswith("/") else src

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

    try:
        page1_data = fetch_event_page(p_tab, FIRST_PAGE_SIZE, page_number)
    except Exception as error:
        print(f"⚠️ {event_type} 탭 1페이지 로드 실패: {error}")
        return products

    for item in parse_item_list(page1_data):
        product = parse_product(item, event_type)
        if product:
            products.append(product)

    while True:
        page_number += 1
        try:
            page_data = fetch_event_page(p_tab, NEXT_PAGE_SIZE, page_number)
        except Exception as error:
            print(f"⚠️ {event_type} 탭 {page_number}페이지 요청 실패: {error}")
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


all_products = []

for p_tab, event_type in EVENT_TABS:
    print(f"\n▶ {event_type} 탭 크롤링 시작...")
    all_products.extend(crawl_tab(p_tab, event_type))

if not all_products:
    raise RuntimeError("저장할 상품이 없습니다.")

save_event_snapshot(STORE_NAME, all_products, meta_key=META_KEY)
print("\n✅ 7-ELEVEN Supabase 크롤링 및 저장 작업 완료.")
