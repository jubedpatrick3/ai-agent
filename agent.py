"""
Pharma Brand Detection Agent for Web Interaction Channel.

Pulls URLs from Snowflake, scrapes page content, and uses Claude AI
to detect pharmaceutical brand names and promomat IDs (MAT-*).
"""

import os
import time
import pandas as pd
from config import OUTPUT_DIR, OUTPUT_FILE, REQUEST_DELAY_SECONDS
from snowflake_connector import fetch_web_interactions
from web_scraper import scrape_page
from analyzer import analyze_page


def run_agent():
    """Main agent pipeline: fetch URLs -> scrape -> analyze -> save results."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Step 1: Fetch data from Snowflake
    print("=" * 60)
    print("PHARMA BRAND DETECTION AGENT")
    print("=" * 60)
    print("\n[1/3] Fetching web interaction data from Snowflake...")
    df = fetch_web_interactions()

    if df.empty:
        print("No data found. Exiting.")
        return

    # Deduplicate URLs
    df = df.drop_duplicates(subset=["PAGE_URL"]).reset_index(drop=True)
    print(f"  -> {len(df)} unique URLs to process\n")

    # Step 2 & 3: Scrape and analyze each URL
    print("[2/3] Scraping and analyzing pages...")
    results = []
    total = len(df)

    for idx, row in df.iterrows():
        url = row["PAGE_URL"]
        page_title = row.get("PAGE_TITLE", "")
        print(f"  [{idx + 1}/{total}] {url[:80]}...")

        # Scrape
        scraped = scrape_page(url)

        if not scraped["success"]:
            print(f"    -> FAILED: {scraped['error']}")
            results.append({
                "page_url": url,
                "page_title": page_title,
                "brands_found": "",
                "mat_ids_found": "",
                "confidence": "N/A",
                "notes": f"Scrape failed: {scraped['error']}",
                "scrape_success": False,
            })
            continue

        # Analyze with Claude
        analysis = analyze_page(url, page_title, scraped["text"])

        brands_str = ", ".join(analysis["brands"]) if analysis["brands"] else ""
        mat_ids_str = ", ".join(analysis["mat_ids"]) if analysis["mat_ids"] else ""

        results.append({
            "page_url": url,
            "page_title": page_title,
            "brands_found": brands_str,
            "mat_ids_found": mat_ids_str,
            "confidence": analysis["confidence"],
            "notes": analysis["notes"],
            "scrape_success": True,
        })

        if brands_str or mat_ids_str:
            print(f"    -> Brands: {brands_str or 'None'}")
            print(f"    -> MAT IDs: {mat_ids_str or 'None'}")
        else:
            print(f"    -> No pharma brands or MAT IDs detected")

        # Rate limiting
        time.sleep(REQUEST_DELAY_SECONDS)

    # Step 3: Save results
    print(f"\n[3/3] Saving results...")
    results_df = pd.DataFrame(results)
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILE)
    results_df.to_csv(output_path, index=False)
    print(f"  -> Results saved to {output_path}")

    # Summary
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

    # Save a filtered view with only pages that had findings
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
