"""
Delivery Controller — Manage delivery/shipping settings.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.auth_utils import require_admin, admin_error_response
from datetime import datetime

supabase = get_supabase_client()


async def get_delivery_settings():
    try:
        response = supabase.table("delivery_settings").select("*").limit(1).execute()
        if not response.data:
            return {"free_delivery_threshold": 50.00, "standard_delivery_price": 4.99}
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_delivery_settings(request: Request):
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        allowed = ["free_delivery_threshold", "standard_delivery_price"]
        update_data = {k: v for k, v in body.items() if k in allowed and v is not None}

        if not update_data:
            return JSONResponse({"error": "No valid data"}, status_code=400)

        update_data["updated_at"] = datetime.utcnow().isoformat()
        existing = supabase.table("delivery_settings").select("id").limit(1).execute()

        if existing.data:
            response = supabase.table("delivery_settings").update(update_data).eq("id", existing.data[0]["id"]).execute()
        else:
            response = supabase.table("delivery_settings").insert(update_data).execute()

        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
