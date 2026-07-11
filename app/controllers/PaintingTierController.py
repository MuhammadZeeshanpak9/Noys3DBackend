"""
Painting Tier Controller — CRUD for painting tiers (Small/Medium/Large)
and their size mappings. Supports per-size price overrides.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.auth_utils import require_admin, admin_error_response
from datetime import datetime
from uuid import uuid4

supabase = get_supabase_client()


async def list_tiers():
    """List all painting tiers with their mapped sizes."""
    try:
        tiers_response = supabase.table("painting_tiers").select("*").order("sort_order").execute()
        tiers = tiers_response.data or []

        # Fetch mappings with size details for each tier
        for tier in tiers:
            mappings_response = supabase.table("painting_tier_mappings").select(
                "*, model_sizes(id, size_label, price)"
            ).eq("painting_tier_id", tier["id"]).execute()
            tier["size_mappings"] = mappings_response.data or []

        return tiers
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_tier(tier_id: str):
    """Get a single painting tier with its size mappings."""
    try:
        tier_response = supabase.table("painting_tiers").select("*").eq("id", tier_id).execute()
        if not tier_response.data:
            return JSONResponse({"error": "Painting tier not found"}, status_code=404)

        tier = tier_response.data[0]

        mappings_response = supabase.table("painting_tier_mappings").select(
            "*, model_sizes(id, size_label, price)"
        ).eq("painting_tier_id", tier_id).execute()
        tier["size_mappings"] = mappings_response.data or []

        return tier
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_tier_for_size(size_id: str):
    """Get the painting tier and price for a specific model size."""
    try:
        mapping_response = supabase.table("painting_tier_mappings").select(
            "*, painting_tiers(*)"
        ).eq("model_size_id", size_id).execute()

        if not mapping_response.data:
            return JSONResponse({"error": "No painting tier mapped for this size"}, status_code=404)

        mapping = mapping_response.data[0]
        tier = mapping.get("painting_tiers", {})

        # Use price override if set, otherwise use the tier's base price
        effective_price = mapping.get("price_override") if mapping.get("price_override") is not None else tier.get("price", 0)

        return {
            "tier_id": tier.get("id"),
            "tier_name": tier.get("name"),
            "tier_base_price": tier.get("price"),
            "price_override": mapping.get("price_override"),
            "effective_price": effective_price,
            "model_size_id": size_id
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def create_tier(request: Request):
    """Create a new painting tier. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        name = body.get("name")
        price = body.get("price")

        if not name or price is None:
            return JSONResponse({"error": "name and price are required"}, status_code=400)

        tier = {
            "id": str(uuid4()),
            "name": name,
            "price": float(price),
            "sort_order": body.get("sort_order", 0),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        response = supabase.table("painting_tiers").insert(tier).execute()
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_tier(request: Request, tier_id: str):
    """Update a painting tier. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        allowed_fields = ["name", "price", "sort_order"]
        update_data = {k: v for k, v in body.items() if k in allowed_fields and v is not None}

        if not update_data:
            return JSONResponse({"error": "No valid update data provided"}, status_code=400)

        update_data["updated_at"] = datetime.utcnow().isoformat()

        response = supabase.table("painting_tiers").update(update_data).eq("id", tier_id).execute()
        if not response.data:
            return JSONResponse({"error": "Painting tier not found"}, status_code=404)

        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_tier(request: Request, tier_id: str):
    """Delete a painting tier. Admin only."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        response = supabase.table("painting_tiers").delete().eq("id", tier_id).execute()
        if not response.data:
            return JSONResponse({"error": "Painting tier not found"}, status_code=404)

        return {"message": "Painting tier deleted successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_size_mappings(request: Request, tier_id: str):
    """
    Update which sizes map to this tier. Admin only.
    Body: { "size_ids": ["uuid1", "uuid2", ...] }
    """
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        size_ids = body.get("size_ids", [])

        if not isinstance(size_ids, list):
            return JSONResponse({"error": "size_ids must be an array"}, status_code=400)

        # Remove existing mappings for this tier
        supabase.table("painting_tier_mappings").delete().eq("painting_tier_id", tier_id).execute()

        # Insert new mappings
        if size_ids:
            mappings = [
                {
                    "id": str(uuid4()),
                    "painting_tier_id": tier_id,
                    "model_size_id": sid
                }
                for sid in size_ids
            ]
            supabase.table("painting_tier_mappings").insert(mappings).execute()

        return {"message": f"Updated {len(size_ids)} size mappings for tier"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def set_size_price_override(request: Request, tier_id: str, size_id: str):
    """
    Set or clear a price override for a specific size within a tier. Admin only.
    Body: { "price_override": 18.00 } or { "price_override": null }
    """
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        price_override = body.get("price_override")

        response = supabase.table("painting_tier_mappings").update({
            "price_override": price_override
        }).eq("painting_tier_id", tier_id).eq("model_size_id", size_id).execute()

        if not response.data:
            return JSONResponse({"error": "Mapping not found"}, status_code=404)

        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
