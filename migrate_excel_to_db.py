import pandas as pd
import sqlite3

EXCEL_FILE = "Backup.xlsx"
DATABASE_FILE = "database.db"

df = pd.read_excel(EXCEL_FILE)
df.columns = df.columns.str.strip()

conn = sqlite3.connect(DATABASE_FILE)

df.to_sql(
    "grades",
    conn,
    if_exists="replace",
    index=False
)

conn.close()

print("SUCCESS: Backup.xlsx migrated to database.db")
print(f"Total records migrated: {len(df)}")