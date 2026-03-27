"""
Pharma Brand Detection Agent - Web Interaction Channel

Pulls URLs from Snowflake, scrapes page content, and uses Claude AI
to detect pharmaceutical brand names and promomat IDs (MAT-*).

Usage:
    cp .env.example .env   # fill in credentials
    pip install -r requirements.txt
    python agent.py
"""

import os
import re
import time

import anthropic
import pandas as pd
import requests
import snowflake.connector
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ────────────────────────────────────────────────────────────

SNOWFLAKE_CONFIG = {
    "account": os.getenv("SNOWFLAKE_ACCOUNT"),
    "user": os.getenv("SNOWFLAKE_USER"),
    "password": os.getenv("SNOWFLAKE_PASSWORD"),
    "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
    "database": os.getenv("SNOWFLAKE_DATABASE", "DF_CI_PROD"),
    "schema": os.getenv("SNOWFLAKE_SCHEMA", "DMT_CIA_SS"),
    "role": os.getenv("SNOWFLAKE_ROLE"),
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

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


# ── Snowflake ────────────────────────────────────────────────────────────────

def fetch_web_interactions() -> pd.DataFrame:
    conn = snowflake.connector.connect(**SNOWFLAKE_CONFIG)
    try:
        cursor = conn.cursor()
        cursor.execute(WEB_INTERACTION_QUERY)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        df = pd.DataFrame(rows, columns=columns)
        print(f"Fetched {len(df)} rows from Snowflake")
        return df
    finally:
        conn.close()


# ── Web Scraper ──────────────────────────────────────────────────────────────

def scrape_page(url: str) -> dict:
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=True)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)[:15000]
            return {"url": url, "success": True, "text": text, "error": None}
        except requests.RequestException as e:
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY_SECONDS)
                continue
            return {"url": url, "success": False, "text": "", "error": str(e)}
    return {"url": url, "success": False, "text": "", "error": "Max retries exceeded"}


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
            "confidence": "N/A", "notes": "Empty page content", "raw_response": "",
        }

    regex_mat_ids = re.findall(r"MAT[-\s]?[A-Z0-9\-]+", page_content, re.IGNORECASE)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(
                url=url, page_title=page_title, content=page_content
            ),
        }],
    )

    raw = message.content[0].text
    result = parse_analysis_response(raw)
    result["url"] = url
    result["page_title"] = page_title
    result["raw_response"] = raw

    all_mat_ids = set(result["mat_ids"])
    for mat_id in regex_mat_ids:
        cleaned = mat_id.strip()
        if cleaned and len(cleaned) > 4:
            all_mat_ids.add(cleaned)
    result["mat_ids"] = sorted(all_mat_ids)

    return result


# ── Main Agent Pipeline ──────────────────────────────────────────────────────

def run_agent():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("PHARMA BRAND DETECTION AGENT")
    print("=" * 60)

    print("\n[1/3] Fetching web interaction data from Snowflake...")
    df = fetch_web_interactions()
    if df.empty:
        print("No data found. Exiting.")
        return

    df = df.drop_duplicates(subset=["PAGE_URL"]).reset_index(drop=True)
    print(f"  -> {len(df)} unique URLs to process\n")

    print("[2/3] Scraping and analyzing pages...")
    results = []
    total = len(df)

    for idx, row in df.iterrows():
        url = row["PAGE_URL"]
        page_title = row.get("PAGE_TITLE", "")
        print(f"  [{idx + 1}/{total}] {url[:80]}...")

        scraped = scrape_page(url)
        if not scraped["success"]:
            print(f"    -> FAILED: {scraped['error']}")
            results.append({
                "page_url": url, "page_title": page_title, "brands_found": "",
                "mat_ids_found": "", "confidence": "N/A",
                "notes": f"Scrape failed: {scraped['error']}", "scrape_success": False,
            })
            continue

        analysis = analyze_page(url, page_title, scraped["text"])
        brands_str = ", ".join(analysis["brands"]) if analysis["brands"] else ""
        mat_ids_str = ", ".join(analysis["mat_ids"]) if analysis["mat_ids"] else ""

        results.append({
            "page_url": url, "page_title": page_title, "brands_found": brands_str,
            "mat_ids_found": mat_ids_str, "confidence": analysis["confidence"],
            "notes": analysis["notes"], "scrape_success": True,
        })

        if brands_str or mat_ids_str:
            print(f"    -> Brands: {brands_str or 'None'}")
            print(f"    -> MAT IDs: {mat_ids_str or 'None'}")
        else:
            print(f"    -> No pharma brands or MAT IDs detected")

        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\n[3/3] Saving results...")
    results_df = pd.DataFrame(results)
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    results_df.to_csv(output_path, index=False)
    print(f"  -> Results saved to {output_path}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_processed = len(results)
    success_count = sum(1 for r in results if r["scrape_success"])
    brand_count = sum(1 for r in results if r["brands_found"])
    mat_count = sum(1 for r in results if r["mat_ids_found"])
    print(f"  Total URLs processed: {total_processed}")
    print(f"  Successfully scraped: {success_count}")
    print(f"  Pages with brands:    {brand_count}")
    print(f"  Pages with MAT IDs:   {mat_count}")

    findings_df = results_df[
        (results_df["brands_found"] != "") | (results_df["mat_ids_found"] != "")
    ]
    if not findings_df.empty:
        findings_path = os.path.join(OUTPUT_DIR, "pharma_findings_only.csv")
        findings_df.to_csv(findings_path, index=False)
        print(f"\n  Filtered results (findings only) saved to {findings_path}")
    else:
        print("\n  No pharma brands or MAT IDs were detected in any pages.")


if __name__ == "__main__":
    run_agent()
