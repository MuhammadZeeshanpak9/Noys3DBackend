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


async def create_order(request: Request):
    
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        
        body = await request.json()
        items = body.get("items", [])
        shipping_address = body.get("shipping_address")
        
        if not items or not shipping_address:
            return JSONResponse({"error": "Items and shipping address are required"}, status_code=400)

        total = sum(item.get("price", 0) * item.get("quantity", 1) for item in items)
        
        order = {
            "id": str(uuid4()),
            "user_id": current_user["id"],
            "items": items,
            "total": total,
            "status": "pending",
            "shipping_address": shipping_address,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        response = supabase.table("orders").insert(order).execute()
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def list_orders(request: Request):
    
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        
        response = supabase.table("orders").select("*").eq("user_id", current_user["id"]).order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_order(request: Request, order_id: str):
    
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        is_admin = current_user.get("role") == "admin"
        
        query = supabase.table("orders").select("*").eq("id", order_id)
        if not is_admin:
            query = query.eq("user_id", current_user["id"])
        
        response = query.execute()
        if not response.data:
            return JSONResponse({"error": "Order not found"}, status_code=404)
        
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_order_status(request: Request, order_id: str):
    
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        
        if current_user.get("role") != "admin":
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        body = await request.json()
        status = body.get("status")
        
        valid_statuses = ["pending", "processing", "shipped", "delivered", "cancelled"]
        if status not in valid_statuses:
            return JSONResponse({"error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}, status_code=400)
        
        update_data = {
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        }
        
        response = supabase.table("orders").update(update_data).eq("id", order_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "Order not found"}, status_code=404)
        
        return {"message": f"Order status updated to {status}"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
