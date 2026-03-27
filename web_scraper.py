import time
import requests
from bs4 import BeautifulSoup
from config import REQUEST_TIMEOUT, MAX_RETRIES, REQUEST_DELAY_SECONDS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def scrape_page(url: str) -> dict:
    """Scrape a URL and return extracted text content.

    Returns a dict with keys: url, success, text, error
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.get(
                url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=True
            )
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            # Remove scripts and styles
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)

            # Truncate to ~15k chars to stay within API limits
            text = text[:15000]

            return {"url": url, "success": True, "text": text, "error": None}

        except requests.RequestException as e:
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY_SECONDS)
                continue
            return {"url": url, "success": False, "text": "", "error": str(e)}

    return {"url": url, "success": False, "text": "", "error": "Max retries exceeded"}
