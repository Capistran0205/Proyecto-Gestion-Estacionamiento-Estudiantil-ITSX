"""Cliente único de Supabase compartido por los servicios."""

from functools import lru_cache

from supabase import Client, create_client

from parking_app.core.config import get_settings


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)
