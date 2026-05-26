import os
import pandas as pd
import sqlite3
from sqlalchemy import create_engine

SQLITE_FILE = "database.db"

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set.")
    exit()

sqlite_conn = sqlite3.connect(SQLITE_FILE)
df = pd.read_sql_query("SELECT * FROM grades", sqlite_conn)
sqlite_conn.close()

print(f"Loaded {len(df)} rows from SQLite.")

engine = create_engine(DATABASE_URL)

df.to_sql(
    "grades",
    engine,
    if_exists="replace",
    index=False
)

print("Migration complete. SQLite data copied to PostgreSQL.")