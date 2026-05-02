"""
Finish Option Controller — CRUD for finish/package options (Unpainted, DIY Kit, Painted).
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.auth_utils import require_admin, admin_error_response
from datetime import datetime
from uuid import uuid4

supabase = get_supabase_client()


async def list_finishes(active_only: bool = True):
    """List all finish options, ordered by sort_order."""
    try:
        query = supabase.table("finish_options").select("*")
        if active_only:
            query = query.eq("is_active", True)
        response = query.order("sort_order").execute()
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_finish(finish_id: str):
    """Get a single finish option by ID."""
    try:
        response = supabase.table("finish_options").select("*").eq("id", finish_id).execute()
        if not response.data:
            return JSONResponse({"error": "Finish option not found"}, status_code=404)
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def create_finish(request: Request):
    """Create a new finish option. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        name = body.get("name")
        slug = body.get("slug")

        if not name or not slug:
            return JSONResponse({"error": "name and slug are required"}, status_code=400)

        finish = {
            "id": str(uuid4()),
            "name": name,
            "slug": slug,
            "description": body.get("description"),
            "base_price": float(body.get("base_price", 0)),
            "is_on_sale": body.get("is_on_sale", False),
            "sale_price": body.get("sale_price"),
            "is_active": body.get("is_active", True),
            "sort_order": body.get("sort_order", 0),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        response = supabase.table("finish_options").insert(finish).execute()
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_finish(request: Request, finish_id: str):
    """Update a finish option. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        allowed_fields = ["name", "slug", "description", "base_price", "is_on_sale", "sale_price", "is_active", "sort_order"]
        update_data = {k: v for k, v in body.items() if k in allowed_fields and v is not None}

        if not update_data:
            return JSONResponse({"error": "No valid update data provided"}, status_code=400)

        update_data["updated_at"] = datetime.utcnow().isoformat()

        response = supabase.table("finish_options").update(update_data).eq("id", finish_id).execute()
        if not response.data:
            return JSONResponse({"error": "Finish option not found"}, status_code=404)

        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_finish(request: Request, finish_id: str):
    """Delete a finish option. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        response = supabase.table("finish_options").delete().eq("id", finish_id).execute()
        if not response.data:
            return JSONResponse({"error": "Finish option not found"}, status_code=404)

        return {"message": "Finish option deleted successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
