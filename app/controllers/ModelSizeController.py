"""
Model Size Controller — CRUD for model sizes (scale labels, e.g. "1:12 Scale") with individually editable prices.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.auth_utils import require_admin, admin_error_response
from datetime import datetime
from uuid import uuid4

supabase = get_supabase_client()


async def list_sizes(active_only: bool = True):
    """List all model sizes, ordered by sort_order."""
    try:
        query = supabase.table("model_sizes").select("*")
        if active_only:
            query = query.eq("is_active", True)
        response = query.order("sort_order").execute()
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_size(size_id: str):
    """Get a single model size by ID."""
    try:
        response = supabase.table("model_sizes").select("*").eq("id", size_id).execute()
        if not response.data:
            return JSONResponse({"error": "Size not found"}, status_code=404)
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def create_size(request: Request):
    """Create a new model size. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        size_label = body.get("size_label")
        price = body.get("price")

        if not size_label or price is None:
            return JSONResponse({"error": "size_label and price are required"}, status_code=400)

        size = {
            "id": str(uuid4()),
            "size_label": str(size_label).strip(),
            "price": float(price),
            "is_on_sale": body.get("is_on_sale", False),
            "sale_price": body.get("sale_price"),
            "is_active": body.get("is_active", True),
            "sort_order": body.get("sort_order", 0),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        response = supabase.table("model_sizes").insert(size).execute()
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_size(request: Request, size_id: str):
    """Update a model size. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        allowed_fields = ["size_label", "price", "is_on_sale", "sale_price", "is_active", "sort_order"]
        update_data = {k: v for k, v in body.items() if k in allowed_fields and v is not None}

        if not update_data:
            return JSONResponse({"error": "No valid update data provided"}, status_code=400)

        update_data["updated_at"] = datetime.utcnow().isoformat()

        response = supabase.table("model_sizes").update(update_data).eq("id", size_id).execute()
        if not response.data:
            return JSONResponse({"error": "Size not found"}, status_code=404)

        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_size(request: Request, size_id: str):
    """Delete a model size. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        response = supabase.table("model_sizes").delete().eq("id", size_id).execute()
        if not response.data:
            return JSONResponse({"error": "Size not found"}, status_code=404)

        return {"message": "Size deleted successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
