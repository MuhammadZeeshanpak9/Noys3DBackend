from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.security import decode_access_token
from datetime import datetime
from uuid import uuid4
from typing import Optional


supabase = get_supabase_client()


def _get_current_user(request: Request) -> Optional[dict]:
    
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    
    token = auth_header.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        return None
    
    user_id = payload.get("sub")
    response = supabase.table("users").select("*").eq("id", user_id).execute()
    
    if not response.data:
        return None
    
    return response.data[0]


def _require_admin(request: Request) -> Optional[dict]:
    
    user = _get_current_user(request)
    if not user:
        return None
    if user.get("role") != "admin":
        return None
    return user


async def list_categories():
    
    try:
        response = supabase.table("categories").select("*").order("name").execute()
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_category(category_id: str):
    
    try:
        response = supabase.table("categories").select("*").eq("id", category_id).execute()
        if not response.data:
            return JSONResponse({"error": "Category not found"}, status_code=404)
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def create_category(request: Request):
    
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        body = await request.json()
        name = body.get("name")
        slug = body.get("slug")
        description = body.get("description")
        
        if not name or not slug:
            return JSONResponse({"error": "Name and slug are required"}, status_code=400)

        existing = supabase.table("categories").select("id").eq("slug", slug).execute()
        if existing.data:
            return JSONResponse({"error": "Category with this slug already exists"}, status_code=400)
        
        category = {
            "id": str(uuid4()),
            "name": name,
            "slug": slug,
            "description": description,
            "created_at": datetime.utcnow().isoformat()
        }
        
        import logging
        logging.info(f"Creating category: {category}")
        
        response = supabase.table("categories").insert(category).execute()
        return response.data[0]
    except Exception as e:
        import logging
        logging.error(f"Error creating category: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_category(request: Request, category_id: str):
    
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        body = await request.json()
        update_data = {k: v for k, v in body.items() if v is not None}
        
        if not update_data:
            return JSONResponse({"error": "No valid update data provided"}, status_code=400)
        
        import logging
        logging.info(f"Updating category {category_id} with: {update_data}")
        
        response = supabase.table("categories").update(update_data).eq("id", category_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "Category not found"}, status_code=404)
        
        return response.data[0]
    except Exception as e:
        import logging
        logging.error(f"Error updating category: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_category(request: Request, category_id: str):
    
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)

        products = supabase.table("products").select("id").eq("category_id", category_id).execute()
        if products.data:
            return JSONResponse({"error": "Cannot delete category with existing products"}, status_code=400)
        
        response = supabase.table("categories").delete().eq("id", category_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "Category not found"}, status_code=404)
        
        return {"message": "Category deleted successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _fetch_colours_for_products(product_ids: list) -> dict:
    """Return {product_id: [colour_row, ...]} ordered by sort_order."""
    if not product_ids:
        return {}
    rows = (
        supabase.table("product_colours")
        .select("*")
        .in_("product_id", product_ids)
        .order("sort_order")
        .execute()
        .data
        or []
    )
    by_pid: dict = {}
    for r in rows:
        by_pid.setdefault(r["product_id"], []).append(r)
    return by_pid


def _replace_product_colours(product_id: str, colours: list) -> None:
    """Wipe existing colour rows for this product and insert the new list.
    `colours` is a list of {name, hex_code, sort_order?} dicts."""
    supabase.table("product_colours").delete().eq("product_id", product_id).execute()
    if not colours:
        return
    rows = []
    for idx, c in enumerate(colours):
        name = (c or {}).get("name", "").strip()
        hex_code = (c or {}).get("hex_code", "").strip()
        if not name or not hex_code:
            continue
        rows.append({
            "id": str(uuid4()),
            "product_id": product_id,
            "name": name,
            "hex_code": hex_code,
            "sort_order": int((c or {}).get("sort_order", idx)),
            "created_at": datetime.utcnow().isoformat(),
        })
    if rows:
        supabase.table("product_colours").insert(rows).execute()


def _fetch_media_for_products(product_ids: list) -> dict:
    """Return {product_id: [media_row, ...]} ordered by sort_order."""
    if not product_ids:
        return {}
    rows = (
        supabase.table("product_media")
        .select("*")
        .in_("product_id", product_ids)
        .order("sort_order")
        .execute()
        .data
        or []
    )
    by_pid: dict = {}
    for r in rows:
        by_pid.setdefault(r["product_id"], []).append(r)
    return by_pid


def _replace_product_media(product_id: str, media: list) -> None:
    """Wipe existing media rows for this product and insert the new list.
    `media` is a list of {url, media_type, sort_order?} dicts."""
    supabase.table("product_media").delete().eq("product_id", product_id).execute()
    if not media:
        return
    rows = []
    for idx, m in enumerate(media):
        url = (m or {}).get("url")
        media_type = (m or {}).get("media_type") or "image"
        if not url:
            continue
        rows.append({
            "id": str(uuid4()),
            "product_id": product_id,
            "url": url,
            "media_type": media_type if media_type in ("image", "video") else "image",
            "sort_order": int((m or {}).get("sort_order", idx)),
            "created_at": datetime.utcnow().isoformat(),
        })
    if rows:
        supabase.table("product_media").insert(rows).execute()


async def list_products(category: Optional[str] = None, active_only: bool = True):

    try:
        query = supabase.table("products").select("*")

        if active_only:
            query = query.eq("is_active", True)

        if category:
            cat_response = supabase.table("categories").select("id").eq("slug", category).execute()
            if cat_response.data:
                query = query.eq("category_id", cat_response.data[0]["id"])

        response = query.order("created_at", desc=True).execute()
        products = response.data or []
        pids = [p["id"] for p in products]
        media_by_pid = _fetch_media_for_products(pids)
        colours_by_pid = _fetch_colours_for_products(pids)
        for p in products:
            p["media"] = media_by_pid.get(p["id"], [])
            p["colours"] = colours_by_pid.get(p["id"], [])
        return products
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_product(product_id: str):

    try:
        response = supabase.table("products").select("*").eq("id", product_id).execute()
        if not response.data:
            return JSONResponse({"error": "Product not found"}, status_code=404)
        product = response.data[0]
        product["media"] = _fetch_media_for_products([product_id]).get(product_id, [])
        product["colours"] = _fetch_colours_for_products([product_id]).get(product_id, [])
        return product
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def create_product(request: Request):

    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)

        body = await request.json()
        name = body.get("name")
        price = body.get("price")

        if not name or not price:
            return JSONResponse({"error": "Name and price are required"}, status_code=400)

        category_ids = body.pop("category_ids", None)
        category_id = None
        if category_ids and isinstance(category_ids, list) and len(category_ids) > 0:
            category_id = category_ids[0]

        is_active = True
        if "status" in body:
            is_active = body["status"] == "active"
            body.pop("status", None)

        media = body.pop("media", None)
        colours = body.pop("colours", None)
        scale_variations = body.pop("scale_variations", None)

        # Derive thumbnail (image_url) from the first image in media[] if not provided.
        image_url = body.get("image_url")
        if not image_url and isinstance(media, list):
            for m in media:
                if (m or {}).get("media_type") == "image" and (m or {}).get("url"):
                    image_url = m["url"]
                    break

        product_id = str(uuid4())
        product = {
            "id": product_id,
            "name": name,
            "description": body.get("description"),
            "price": price,
            "image_url": image_url,
            "category_id": category_id or body.get("category_id"),
            "is_active": is_active,
            "scale_variations": scale_variations,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        import logging
        logging.info(f"Creating product with data: {product}")

        response = supabase.table("products").insert(product).execute()
        created = response.data[0] if response.data else product

        if isinstance(media, list):
            _replace_product_media(product_id, media)

        if isinstance(colours, list):
            _replace_product_colours(product_id, colours)

        created["media"] = _fetch_media_for_products([product_id]).get(product_id, [])
        created["colours"] = _fetch_colours_for_products([product_id]).get(product_id, [])
        return created
    except Exception as e:
        import logging
        logging.error(f"Error creating product: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_product(request: Request, product_id: str):

    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)

        body = await request.json()

        if "category_ids" in body:
            category_ids = body.pop("category_ids")
            if category_ids and isinstance(category_ids, list) and len(category_ids) > 0:
                body["category_id"] = category_ids[0]

        if "status" in body:
            body["is_active"] = body["status"] == "active"
            body.pop("status", None)

        media = body.pop("media", None)
        colours = body.pop("colours", None)
        _scale_provided = "scale_variations" in body
        scale_variations = body.pop("scale_variations", None)

        # If client sent media[] but no explicit image_url, sync the thumbnail
        # to the first image so shop cards stay accurate.
        if isinstance(media, list) and "image_url" not in body:
            primary = next(
                (m["url"] for m in media if (m or {}).get("media_type") == "image" and (m or {}).get("url")),
                None,
            )
            body["image_url"] = primary

        update_data = {k: v for k, v in body.items() if v is not None or k == "image_url"}
        update_data["updated_at"] = datetime.utcnow().isoformat()
        if _scale_provided:
            update_data["scale_variations"] = scale_variations  # allow None to disable

        import logging
        logging.info(f"Updating product {product_id} with data: {update_data}")

        response = supabase.table("products").update(update_data).eq("id", product_id).execute()

        if not response.data:
            return JSONResponse({"error": "Product not found"}, status_code=404)

        if isinstance(media, list):
            _replace_product_media(product_id, media)

        if isinstance(colours, list):
            _replace_product_colours(product_id, colours)

        result = response.data[0]
        result["media"] = _fetch_media_for_products([product_id]).get(product_id, [])
        result["colours"] = _fetch_colours_for_products([product_id]).get(product_id, [])
        return result
    except Exception as e:
        import logging
        logging.error(f"Error updating product: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_product(request: Request, product_id: str):
    
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        response = supabase.table("products").delete().eq("id", product_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "Product not found"}, status_code=404)
        
        return {"message": "Product deleted successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
