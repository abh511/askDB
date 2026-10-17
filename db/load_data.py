"""Load the Olist CSVs from data/raw/ into PostgreSQL (run once, as the admin user)."""
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from askdb.config import settings

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

# Kaggle file name -> table name
CSV_TO_TABLE = {
    "olist_customers_dataset.csv": "customers",
    "olist_geolocation_dataset.csv": "geolocation",
    "olist_orders_dataset.csv": "orders",
    "olist_order_items_dataset.csv": "order_items",
    "olist_order_payments_dataset.csv": "order_payments",
    "olist_order_reviews_dataset.csv": "order_reviews",
    "olist_products_dataset.csv": "products",
    "olist_sellers_dataset.csv": "sellers",
    "product_category_name_translation.csv": "category_translation",
}


def main() -> None:
    engine = create_engine(settings.database_admin_url)
    for csv_name, table in CSV_TO_TABLE.items():
        path = RAW / csv_name
        if not path.exists():
            print(f"skip  {csv_name} (not found in {RAW})")
            continue
        # zip prefixes keep their leading zeros as text
        df = pd.read_csv(path, dtype={c: str for c in pd.read_csv(path, nrows=0).columns
                                      if "zip_code_prefix" in c})
        # date columns arrive as text; Postgres won't put VARCHAR into a TIMESTAMP column
        for col in df.columns:
            if col.endswith(("_date", "_timestamp", "_at")):
                df[col] = pd.to_datetime(df[col])
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {table}"))
        # one multi-row INSERT sends rows x columns parameters; Postgres allows at most 65,535
        chunksize = 65_535 // len(df.columns)
        df.to_sql(table, engine, if_exists="append", index=False, chunksize=chunksize, method="multi")
        print(f"load  {table:<22} {len(df):>8,} rows")


if __name__ == "__main__":
    main()
