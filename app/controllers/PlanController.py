from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.security import decode_access_token
from datetime import datetime
from uuid import uuid4
from typing import Optional
import json


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


async def list_plans():
    
    try:
        response = supabase.table("plans").select("*").order("price").execute()
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_plan(plan_id: str):
    
    try:
        response = supabase.table("plans").select("*").eq("id", plan_id).execute()
        if not response.data:
            return JSONResponse({"error": "Plan not found"}, status_code=404)
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def create_plan(request: Request):
    
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        body = await request.json()
        name = body.get("name")
        price = body.get("price")
        credits = body.get("credits")
        
        if not name or not price or not credits:
            return JSONResponse({"error": "Name, price, and credits are required"}, status_code=400)

        features = body.get("features", [])
        if features is None:
            features = []
        elif isinstance(features, str):
            features = [features]
        
        plan = {
            "id": str(uuid4()),
            "name": name,
            "price": price,
            "credits": credits,
            "features": features,
            "is_popular": body.get("is_popular", False),
            "stripe_price_id": body.get("stripe_price_id"),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        import logging
        logging.info(f"Creating plan: {plan}")
        
        response = supabase.table("plans").insert(plan).execute()
        return response.data[0]
    except Exception as e:
        import logging
        logging.error(f"Error creating plan: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_plan(request: Request, plan_id: str):
    
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        body = await request.json()
        update_data = {k: v for k, v in body.items() if v is not None}

        if "features" in update_data:
            if update_data["features"] is None:
                update_data["features"] = []
            elif isinstance(update_data["features"], str):
                update_data["features"] = [update_data["features"]]
        
        if not update_data:
            return JSONResponse({"error": "No valid update data provided"}, status_code=400)
        
        update_data["updated_at"] = datetime.utcnow().isoformat()
        
        import logging
        logging.info(f"Updating plan {plan_id} with: {update_data}")
        
        response = supabase.table("plans").update(update_data).eq("id", plan_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "Plan not found"}, status_code=404)
        
        return response.data[0]
    except Exception as e:
        import logging
        logging.error(f"Error updating plan: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_plan(request: Request, plan_id: str):
    
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        response = supabase.table("plans").delete().eq("id", plan_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "Plan not found"}, status_code=404)
        
        return {"message": "Plan deleted successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def list_credit_packs(active_only: bool = True):
    
    try:
        query = supabase.table("credit_packs").select("*")
        
        if active_only:
            query = query.eq("is_active", True)
        
        response = query.order("credits").execute()
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_credit_pack(pack_id: str):
    
    try:
        response = supabase.table("credit_packs").select("*").eq("id", pack_id).execute()
        if not response.data:
            return JSONResponse({"error": "Credit pack not found"}, status_code=404)
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def create_credit_pack(request: Request):
    
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        body = await request.json()
        credits = body.get("credits")
        price = body.get("price")
        
        if not credits or not price:
            return JSONResponse({"error": "Credits and price are required"}, status_code=400)
        
        pack = {
            "id": str(uuid4()),
            "credits": credits,
            "price": price,
            "stripe_price_id": body.get("stripe_price_id"),
            "is_active": body.get("is_active", True),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        import logging
        logging.info(f"Creating credit pack: {pack}")
        
        response = supabase.table("credit_packs").insert(pack).execute()
        return response.data[0]
    except Exception as e:
        import logging
        logging.error(f"Error creating credit pack: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_credit_pack(request: Request, pack_id: str):
    
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        body = await request.json()
        update_data = {k: v for k, v in body.items() if v is not None}
        
        if not update_data:
            return JSONResponse({"error": "No valid update data provided"}, status_code=400)
        
        update_data["updated_at"] = datetime.utcnow().isoformat()
        
        import logging
        logging.info(f"Updating credit pack {pack_id} with: {update_data}")
        
        response = supabase.table("credit_packs").update(update_data).eq("id", pack_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "Credit pack not found"}, status_code=404)
        
        return response.data[0]
    except Exception as e:
        import logging
        logging.error(f"Error updating credit pack: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_credit_pack(request: Request, pack_id: str):
    
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        response = supabase.table("credit_packs").delete().eq("id", pack_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "Credit pack not found"}, status_code=404)
        
        return {"message": "Credit pack deleted successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
