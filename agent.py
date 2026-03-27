"""
Pharma Brand Detection Agent - Web Interaction Channel

Pulls URLs from Snowflake, scrapes page content, and uses Claude AI
to detect pharmaceutical brand names and promomat IDs (MAT-*).

ZERO external dependencies - uses only Python standard library.
Snowflake connector is the only exception (already available on company tools).

Usage:
    Set environment variables (or edit the config section below), then:
    python agent.py
"""

import csv
import json
import os
import re
import ssl
import time
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ── Configuration ────────────────────────────────────────────────────────────
# Edit these directly OR set matching environment variables

SNOWFLAKE_CONFIG = {
    "account": os.getenv("SNOWFLAKE_ACCOUNT", ""),
    "user": os.getenv("SNOWFLAKE_USER", ""),
    "password": os.getenv("SNOWFLAKE_PASSWORD", ""),
    "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", ""),
    "database": os.getenv("SNOWFLAKE_DATABASE", "DF_CI_PROD"),
    "schema": os.getenv("SNOWFLAKE_SCHEMA", "DMT_CIA_SS"),
    "role": os.getenv("SNOWFLAKE_ROLE", ""),
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

WEB_INTERACTION_QUERY = """
SELECT page_url, page_title
FROM DF_CI_PROD.DMT_CIA_SS.FCT_HQ_WEB_INTERACTION
WHERE INTERACTION_DT >= '2025-01-01' AND INTERACTION_DT < '2027-01-01'
"""

REQUEST_TIMEOUT = 30
MAX_RETRIES = 2
REQUEST_DELAY_SECONDS = 1
OUTPUT_DIR = "output"
OUTPUT_FILE = "pharma_brand_detection_results.csv"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

SYSTEM_PROMPT = """You are a pharmaceutical brand detection specialist. Your job is to analyze web page content and identify:

1. **Pharma Brand Names**: Any pharmaceutical drug brand names, product names, or therapy names mentioned on the page. Include both branded and generic names if present.

2. **Promomat IDs**: Alphanumeric codes that start with "MAT" (e.g., MAT-US-2401234, MAT-1234567, MAT12345). These are promotional material tracking IDs used in the pharmaceutical industry.

Rules:
- Only report brand names that are actual pharmaceutical/biotech products or therapies.
- Do not include company names (like Pfizer, Novartis) unless they are part of a product name.
- For MAT IDs, capture the full ID including any suffixes (e.g., MAT-US-2401234-v1).
- If you find nothing, say so explicitly."""

USER_PROMPT_TEMPLATE = """Analyze the following web page content and extract:
1. All pharmaceutical brand names found
2. All promomat IDs (codes starting with "MAT")

Page URL: {url}
Page Title: {page_title}

--- PAGE CONTENT ---
{content}
--- END CONTENT ---

Respond in this exact format:
BRANDS: brand1, brand2, brand3 (or NONE if no brands found)
MAT_IDS: MAT-xxx, MAT-yyy (or NONE if no MAT IDs found)
CONFIDENCE: HIGH/MEDIUM/LOW
NOTES: Any relevant context about the findings"""


# ── HTML Parser (stdlib replacement for BeautifulSoup) ───────────────────────

class TextExtractor(HTMLParser):
    """Extract visible text from HTML, skipping script/style/nav/footer/header."""

    SKIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._pieces = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._pieces.append(text)

    def get_text(self):
        return "\n".join(self._pieces)


def extract_text_from_html(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    return parser.get_text()[:15000]


# ── Snowflake ────────────────────────────────────────────────────────────────

def fetch_web_interactions() -> list:
    """Fetch page_url and page_title from Snowflake. Returns list of dicts."""
    import snowflake.connector  # available on company tools

    config = {k: v for k, v in SNOWFLAKE_CONFIG.items() if v}
    conn = snowflake.connector.connect(**config)
    try:
        cursor = conn.cursor()
        cursor.execute(WEB_INTERACTION_QUERY)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        data = [dict(zip(columns, row)) for row in rows]
        print(f"Fetched {len(data)} rows from Snowflake")
        return data
    finally:
        conn.close()


# ── Web Scraper (stdlib urllib) ──────────────────────────────────────────────

def scrape_page(url: str) -> dict:
    """Scrape a URL using only stdlib urllib."""
    ctx = ssl.create_default_context()

    for attempt in range(MAX_RETRIES + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
                raw = resp.read()
                # try utf-8 first, fall back to latin-1
                try:
                    html = raw.decode("utf-8")
                except UnicodeDecodeError:
                    html = raw.decode("latin-1")
            text = extract_text_from_html(html)
            return {"url": url, "success": True, "text": text, "error": None}
        except (URLError, HTTPError, OSError) as e:
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY_SECONDS)
                continue
            return {"url": url, "success": False, "text": "", "error": str(e)}
    return {"url": url, "success": False, "text": "", "error": "Max retries exceeded"}


# ── Claude API (stdlib urllib, no anthropic SDK) ─────────────────────────────

def call_claude_api(system: str, user_message: str) -> str:
    """Call the Anthropic Messages API using only stdlib."""
    url = "https://api.anthropic.com/v1/messages"
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "system": system,
        "messages": [{"role": "user", "content": user_message}],
    }).encode("utf-8")

    req = Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", ANTHROPIC_API_KEY)
    req.add_header("anthropic-version", "2023-06-01")

    ctx = ssl.create_default_context()
    with urlopen(req, timeout=60, context=ctx) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    return body["content"][0]["text"]


# ── AI Analyzer ──────────────────────────────────────────────────────────────

def parse_analysis_response(response_text: str) -> dict:
    result = {"brands": [], "mat_ids": [], "confidence": "UNKNOWN", "notes": ""}
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("BRANDS:"):
            value = line[len("BRANDS:"):].strip()
            if value.upper() != "NONE":
                result["brands"] = [b.strip() for b in value.split(",") if b.strip()]
        elif line.startswith("MAT_IDS:"):
            value = line[len("MAT_IDS:"):].strip()
            if value.upper() != "NONE":
                result["mat_ids"] = [m.strip() for m in value.split(",") if m.strip()]
        elif line.startswith("CONFIDENCE:"):
            result["confidence"] = line[len("CONFIDENCE:"):].strip()
        elif line.startswith("NOTES:"):
            result["notes"] = line[len("NOTES:"):].strip()
    return result


def analyze_page(url: str, page_title: str, page_content: str) -> dict:
    if not page_content.strip():
        return {
            "url": url, "page_title": page_title, "brands": [], "mat_ids": [],
            "confidence": "N/A", "notes": "Empty page content",
        }

    # Regex pre-scan for MAT IDs
    regex_mat_ids = re.findall(r"MAT[-\s]?[A-Z0-9\-]+", page_content, re.IGNORECASE)

    user_msg = USER_PROMPT_TEMPLATE.format(
        url=url, page_title=page_title, content=page_content
    )
    raw = call_claude_api(SYSTEM_PROMPT, user_msg)
    result = parse_analysis_response(raw)
    result["url"] = url
    result["page_title"] = page_title

    # Merge regex-found MAT IDs with AI-found ones
    all_mat_ids = set(result["mat_ids"])
    for mat_id in regex_mat_ids:
        cleaned = mat_id.strip()
        if cleaned and len(cleaned) > 4:
            all_mat_ids.add(cleaned)
    result["mat_ids"] = sorted(all_mat_ids)

    return result


# ── CSV Writer (stdlib replacement for pandas) ──────────────────────────────

def write_csv(filepath: str, rows: list):
    """Write list of dicts to CSV using stdlib csv module."""
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ── Main Agent Pipeline ──────────────────────────────────────────────────────

def run_agent():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("PHARMA BRAND DETECTION AGENT")
    print("=" * 60)

    # Step 1: Fetch from Snowflake
    print("\n[1/3] Fetching web interaction data from Snowflake...")
    data = fetch_web_interactions()
    if not data:
        print("No data found. Exiting.")
        return

    # Deduplicate by PAGE_URL
    seen = set()
    unique_data = []
    for row in data:
        url = row.get("PAGE_URL", "")
        if url and url not in seen:
            seen.add(url)
            unique_data.append(row)
    print(f"  -> {len(unique_data)} unique URLs to process\n")

    # Step 2: Scrape and analyze
    print("[2/3] Scraping and analyzing pages...")
    results = []
    total = len(unique_data)

    for idx, row in enumerate(unique_data):
        url = row.get("PAGE_URL", "")
        page_title = row.get("PAGE_TITLE", "")
        print(f"  [{idx + 1}/{total}] {url[:80]}...")

        scraped = scrape_page(url)
        if not scraped["success"]:
            print(f"    -> FAILED: {scraped['error']}")
            results.append({
                "page_url": url, "page_title": page_title, "brands_found": "",
                "mat_ids_found": "", "confidence": "N/A",
                "notes": f"Scrape failed: {scraped['error']}", "scrape_success": "False",
            })
            continue

        analysis = analyze_page(url, page_title, scraped["text"])
        brands_str = ", ".join(analysis["brands"]) if analysis["brands"] else ""
        mat_ids_str = ", ".join(analysis["mat_ids"]) if analysis["mat_ids"] else ""

        results.append({
            "page_url": url, "page_title": page_title, "brands_found": brands_str,
            "mat_ids_found": mat_ids_str, "confidence": analysis["confidence"],
            "notes": analysis["notes"], "scrape_success": "True",
        })

        if brands_str or mat_ids_str:
            print(f"    -> Brands: {brands_str or 'None'}")
            print(f"    -> MAT IDs: {mat_ids_str or 'None'}")
        else:
            print("    -> No pharma brands or MAT IDs detected")

        time.sleep(REQUEST_DELAY_SECONDS)

    # Step 3: Save results
    print(f"\n[3/3] Saving results...")
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    write_csv(output_path, results)
    print(f"  -> Results saved to {output_path}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_processed = len(results)
    success_count = sum(1 for r in results if r["scrape_success"] == "True")
    brand_count = sum(1 for r in results if r["brands_found"])
    mat_count = sum(1 for r in results if r["mat_ids_found"])
    print(f"  Total URLs processed: {total_processed}")
    print(f"  Successfully scraped: {success_count}")
    print(f"  Pages with brands:    {brand_count}")
    print(f"  Pages with MAT IDs:   {mat_count}")

    # Filtered findings
    findings = [r for r in results if r["brands_found"] or r["mat_ids_found"]]
    if findings:
        findings_path = os.path.join(OUTPUT_DIR, "pharma_findings_only.csv")
        write_csv(findings_path, findings)
        print(f"\n  Filtered results (findings only) saved to {findings_path}")
    else:
        print("\n  No pharma brands or MAT IDs were detected in any pages.")


if __name__ == "__main__":
    run_agent()
