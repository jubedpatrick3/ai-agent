# Pharma Brand Detection Agent - Web Interaction Channel

AI agent that pulls web interaction URLs from Snowflake, scrapes each page, and uses Claude AI to detect pharmaceutical brand names and promomat IDs (MAT-*).

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your Snowflake and Anthropic credentials
   ```

## Usage

```bash
python agent.py
```

## Pipeline

1. **Snowflake Query** - Fetches `page_url` and `page_title` from `FCT_HQ_WEB_INTERACTION`
2. **Web Scraping** - Opens each URL and extracts text content
3. **AI Analysis** - Claude analyzes content for pharma brand names and MAT IDs
4. **Output** - Results saved to `output/pharma_brand_detection_results.csv`

## Output

- `output/pharma_brand_detection_results.csv` - All processed URLs with findings
- `output/pharma_findings_only.csv` - Only URLs where brands or MAT IDs were detected

## Configuration

Edit `config.py` to adjust:
- Snowflake query and date range
- Request timeout and retry settings
- Output directory and file names
