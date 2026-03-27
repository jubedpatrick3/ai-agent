import re
import anthropic
from config import ANTHROPIC_API_KEY

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are a pharmaceutical brand detection specialist. Your job is to analyze web page content and identify:

1. **Pharma Brand Names**: Any pharmaceutical drug brand names, product names, or therapy names mentioned on the page. Include both branded and generic names if present.

2. **Promomat IDs**: Alphanumeric codes that start with "MAT" (e.g., MAT-US-2401234, MAT-1234567, MAT12345). These are promotional material tracking IDs used in the pharmaceutical industry.

Rules:
- Only report brand names that are actual pharmaceutical/biotech products or therapies.
- Do not include company names (like Pfizer, Novartis) unless they are part of a product name.
- For MAT IDs, capture the full ID including any suffixes (e.g., MAT-US-2401234-v1).
- If you find nothing, say so explicitly.
"""

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
NOTES: Any relevant context about the findings
"""


def analyze_page(url: str, page_title: str, page_content: str) -> dict:
    """Use Claude to analyze page content for pharma brands and MAT IDs."""
    if not page_content.strip():
        return {
            "url": url,
            "page_title": page_title,
            "brands": [],
            "mat_ids": [],
            "confidence": "N/A",
            "notes": "Empty page content",
            "raw_response": "",
        }

    # Pre-scan for MAT IDs with regex as a supplementary check
    regex_mat_ids = re.findall(r"MAT[-\s]?[A-Z0-9\-]+", page_content, re.IGNORECASE)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(
                    url=url, page_title=page_title, content=page_content
                ),
            }
        ],
    )

    raw = message.content[0].text
    result = parse_analysis_response(raw)
    result["url"] = url
    result["page_title"] = page_title
    result["raw_response"] = raw

    # Merge regex-found MAT IDs with AI-found ones
    all_mat_ids = set(result["mat_ids"])
    for mat_id in regex_mat_ids:
        cleaned = mat_id.strip()
        if cleaned and len(cleaned) > 4:
            all_mat_ids.add(cleaned)
    result["mat_ids"] = sorted(all_mat_ids)

    return result


def parse_analysis_response(response_text: str) -> dict:
    """Parse the structured response from Claude."""
    result = {
        "brands": [],
        "mat_ids": [],
        "confidence": "UNKNOWN",
        "notes": "",
    }

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
