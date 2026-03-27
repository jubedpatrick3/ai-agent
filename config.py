import os
from dotenv import load_dotenv

load_dotenv()

# Snowflake configuration
SNOWFLAKE_CONFIG = {
    "account": os.getenv("SNOWFLAKE_ACCOUNT"),
    "user": os.getenv("SNOWFLAKE_USER"),
    "password": os.getenv("SNOWFLAKE_PASSWORD"),
    "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
    "database": os.getenv("SNOWFLAKE_DATABASE", "DF_CI_PROD"),
    "schema": os.getenv("SNOWFLAKE_SCHEMA", "DMT_CIA_SS"),
    "role": os.getenv("SNOWFLAKE_ROLE"),
}

# Anthropic API key
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Query to pull web interaction data
WEB_INTERACTION_QUERY = """
SELECT page_url, page_title
FROM DF_CI_PROD.DMT_CIA_SS.FCT_HQ_WEB_INTERACTION
WHERE INTERACTION_DT >= '2025-01-01' AND INTERACTION_DT < '2027-01-01'
"""

# Web scraping settings
REQUEST_TIMEOUT = 30
MAX_RETRIES = 2
REQUEST_DELAY_SECONDS = 1

# Output
OUTPUT_DIR = "output"
OUTPUT_FILE = "pharma_brand_detection_results.csv"
