"""7-ELEVEN 사이트 공통 HTTP 세션 (헤더·재시도)."""
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.7-eleven.co.kr"
PRESENT_VIEW_URL = f"{BASE_URL}/product/presentView.asp"

MAX_RETRIES = 5
RETRY_BACKOFF = 2
DEFAULT_TIMEOUT = 30


def create_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
        "Referer": PRESENT_VIEW_URL,
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "text/html, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    return session


def request_with_retry(session, method, url, label, **kwargs):
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt >= MAX_RETRIES:
                break
            wait = RETRY_BACKOFF ** attempt
            print(f"⚠️ {label} 요청 실패 ({attempt}/{MAX_RETRIES}): {error}")
            print(f"   {wait}초 후 재시도...")
            time.sleep(wait)
    raise last_error


def warm_up_session(session):
    request_with_retry(session, "GET", PRESENT_VIEW_URL, "행사 페이지 warm-up")
