
import sys
sys.path.insert(0, "D:\\ClientProject\\backend")

from app.db.connection import get_supabase_client
from app.core.config import get_settings
import json

settings = get_settings()
supabase = get_supabase_client()

def create_table(table_name: str, schema: dict):
    
    try:

        print(f"Checking if table '{table_name}' exists...")


        print(f"  Schema for {table_name}: {json.dumps(schema, indent=2)}")
        return True
    except Exception as e:
        print(f"Error creating table {table_name}: {e}")
        return False


def init_tables():
    
    
    tables = {
        "users": ,
        "categories": ,
        "products": ,
        "plans": ,
        "credit_packs": ,
        "orders": ,
        "generations": ,
        "payments": 
    }
    
    print("=" * 60)
    print("Supabase Database Setup")
    print("=" * 60)
    print(f"\nSupabase URL: {settings.supabase_url}")
    print("\nTables to create:")
    print("-" * 40)
    
    for table_name in tables.keys():
        print(f"  - {table_name}")
    
    print("\n" + "=" * 60)
    print("INSTRUCTIONS:")
    print("=" * 60)
    print()
    
    for table_name, sql in tables.items():
        print(f"\n-- {table_name.upper()} --")
        print(sql)
    
    print("\n" + "=" * 60)
    print("After creating tables, you can seed initial data:")
    print("=" * 60)
    
    seed_sql = 
    print(seed_sql)


if __name__ == "__main__":
    init_tables()
