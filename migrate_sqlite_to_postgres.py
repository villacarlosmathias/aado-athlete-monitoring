import pandas as pd
from sqlalchemy import create_engine

sqlite_engine = create_engine("sqlite:///database.db")

postgres_engine = create_engine(
    "postgresql+psycopg2://aado_admin:Aado123!@localhost:5432/aado_db"
)

for table in ["users", "sports", "grades"]:
    print(f"Migrating {table}...")

    df = pd.read_sql_query(
        f'SELECT * FROM "{table}"',
        sqlite_engine
    )

    df.to_sql(
        table,
        postgres_engine,
        if_exists="replace",
        index=False
    )

    print(f"Done {table}: {len(df)} records")

print("Migration completed.")
