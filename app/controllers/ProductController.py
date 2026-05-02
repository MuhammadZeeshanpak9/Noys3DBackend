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
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_product(product_id: str):
    
    try:
        response = supabase.table("products").select("*").eq("id", product_id).execute()
        if not response.data:
            return JSONResponse({"error": "Product not found"}, status_code=404)
        return response.data[0]
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
        
        product = {
            "id": str(uuid4()),
            "name": name,
            "description": body.get("description"),
            "price": price,
            "image_url": body.get("image_url"),
            "category_id": category_id or body.get("category_id"),
            "is_active": is_active,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        import logging
        logging.info(f"Creating product with data: {product}")
        
        response = supabase.table("products").insert(product).execute()
        return response.data[0]
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
        
        update_data = {k: v for k, v in body.items() if v is not None}
        update_data["updated_at"] = datetime.utcnow().isoformat()

        import logging
        logging.info(f"Updating product {product_id} with data: {update_data}")
        
        response = supabase.table("products").update(update_data).eq("id", product_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "Product not found"}, status_code=404)
        
        return response.data[0]
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
