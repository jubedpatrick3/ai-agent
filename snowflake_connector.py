import snowflake.connector
import pandas as pd
from config import SNOWFLAKE_CONFIG, WEB_INTERACTION_QUERY


def get_snowflake_connection():
    """Establish a connection to Snowflake."""
    return snowflake.connector.connect(**SNOWFLAKE_CONFIG)


def fetch_web_interactions() -> pd.DataFrame:
    """Fetch page_url and page_title from the web interaction table."""
    conn = get_snowflake_connection()
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


if __name__ == "__main__":
    df = fetch_web_interactions()
    print(df.head())
