"""
Paint Color Controller — CRUD for available extra paint pot colors.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.auth_utils import require_admin, admin_error_response
from datetime import datetime
from uuid import uuid4

supabase = get_supabase_client()


async def list_colors(active_only: bool = True):
    """List all available paint colors."""
    try:
        query = supabase.table("paint_colors").select("*")
        if active_only:
            query = query.eq("is_active", True)
        response = query.order("sort_order").execute()
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_color(color_id: str):
    """Get a single paint color by ID."""
    try:
        response = supabase.table("paint_colors").select("*").eq("id", color_id).execute()
        if not response.data:
            return JSONResponse({"error": "Paint color not found"}, status_code=404)
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def create_color(request: Request):
    """Create a new paint color. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        name = body.get("name")
        price = body.get("price")

        if not name or price is None:
            return JSONResponse({"error": "name and price are required"}, status_code=400)

        color = {
            "id": str(uuid4()),
            "name": name,
            "hex_code": body.get("hex_code", "#000000"),
            "price": float(price),
            "is_on_sale": body.get("is_on_sale", False),
            "sale_price": body.get("sale_price"),
            "is_active": body.get("is_active", True),
            "sort_order": body.get("sort_order", 0),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        response = supabase.table("paint_colors").insert(color).execute()
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_color(request: Request, color_id: str):
    """Update a paint color. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        allowed_fields = ["name", "hex_code", "price", "is_on_sale", "sale_price", "is_active", "sort_order"]
        update_data = {k: v for k, v in body.items() if k in allowed_fields and v is not None}

        if not update_data:
            return JSONResponse({"error": "No valid update data provided"}, status_code=400)

        update_data["updated_at"] = datetime.utcnow().isoformat()

        response = supabase.table("paint_colors").update(update_data).eq("id", color_id).execute()
        if not response.data:
            return JSONResponse({"error": "Paint color not found"}, status_code=404)

        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_color(request: Request, color_id: str):
    """Delete a paint color. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        response = supabase.table("paint_colors").delete().eq("id", color_id).execute()
        if not response.data:
            return JSONResponse({"error": "Paint color not found"}, status_code=404)

        return {"message": "Paint color deleted successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
