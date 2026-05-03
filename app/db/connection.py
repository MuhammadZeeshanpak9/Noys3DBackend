from supabase import create_client, Client
from app.core.config import get_settings
settings = get_settings()

def get_supabase_client() -> Client:
    key = settings.supabase_service_key if settings.supabase_service_key else settings.supabase_anon_key
    return create_client(settings.supabase_url, key)


supabase: Client = get_supabase_client()
