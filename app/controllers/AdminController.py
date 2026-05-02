from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.security import decode_access_token, get_password_hash
from app.core.config import get_settings
from datetime import datetime
from typing import Optional


supabase = get_supabase_client()
settings = get_settings()


def _get_current_admin(request: Request) -> Optional[dict]:
    
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
    
    user = response.data[0]
    if user.get("role") != "admin":
        return None
    
    return user


async def get_stats(request: Request):
    
    try:
        admin = _get_current_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)

        users_response = supabase.table("users").select("id", count="exact").execute()
        total_users = users_response.count or 0

        orders_response = supabase.table("orders").select("id", count="exact").execute()
        total_orders = orders_response.count or 0

        payments_response = supabase.table("payments").select("amount").eq("status", "completed").execute()
        total_revenue = sum(p.get("amount", 0) for p in payments_response.data) if payments_response.data else 0

        subscriptions_response = supabase.table("users").select("id", count="exact").neq("subscription_plan", "starter").execute()
        active_subscriptions = subscriptions_response.count or 0

        generations_response = supabase.table("generations").select("credits_used").execute()
        total_credits_used = sum(g.get("credits_used", 0) for g in generations_response.data) if generations_response.data else 0
        
        return {
            "total_users": total_users,
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "active_subscriptions": active_subscriptions,
            "total_credits_used": total_credits_used
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def list_users(request: Request, limit: int = 50, offset: int = 0):
    
    try:
        admin = _get_current_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        response = supabase.table("users").select("*").order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_user(request: Request, user_id: str):
    
    try:
        admin = _get_current_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        response = supabase.table("users").select("*").eq("id", user_id).execute()
        if not response.data:
            return JSONResponse({"error": "User not found"}, status_code=404)
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_user(request: Request, user_id: str):
    
    try:
        admin = _get_current_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        body = await request.json()
        update_data = {k: v for k, v in body.items() if v is not None}
        
        if not update_data:
            return JSONResponse({"error": "No valid update data provided"}, status_code=400)
        
        update_data["updated_at"] = datetime.utcnow().isoformat()
        
        response = supabase.table("users").update(update_data).eq("id", user_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "User not found"}, status_code=404)
        
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_user(request: Request, user_id: str):
    
    try:
        admin = _get_current_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)

        if user_id == admin["id"]:
            return JSONResponse({"error": "Cannot delete your own account"}, status_code=400)
        
        response = supabase.table("users").delete().eq("id", user_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "User not found"}, status_code=404)
        
        return {"message": "User deleted successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def list_all_orders(request: Request, limit: int = 50, offset: int = 0, status: Optional[str] = None):
    
    try:
        admin = _get_current_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        query = supabase.table("orders").select("*").order("created_at", desc=True).range(offset, offset + limit - 1)
        
        if status:
            query = query.eq("status", status)
        
        response = query.execute()
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_recent_activity(request: Request, limit: int = 20):
    
    try:
        admin = _get_current_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        activity = []

        generations = supabase.table("generations").select("*, users(email)").order("created_at", desc=True).limit(limit).execute()
        
        for gen in generations.data:
            activity.append({
                "type": "generation",
                "user": gen.get("users", {}).get("email", "Unknown"),
                "action": f"Generated {gen.get('credits_used', 1)} model(s)",
                "time": gen.get("created_at")
            })

        orders = supabase.table("orders").select("*, users(email)").order("created_at", desc=True).limit(limit).execute()
        
        for order in orders.data:
            activity.append({
                "type": "order",
                "user": order.get("users", {}).get("email", "Unknown"),
                "action": f"Placed order #{str(order.get('id', ''))[:8]}",
                "time": order.get("created_at")
            })

        users = supabase.table("users").select("id, email, created_at").order("created_at", desc=True).limit(limit).execute()
        
        for user in users.data:
            activity.append({
                "type": "signup",
                "user": user.get("email"),
                "action": "Signed up",
                "time": user.get("created_at")
            })

        activity.sort(key=lambda x: x.get("time", ""), reverse=True)
        return activity[:limit]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_settings(request: Request):
    
    try:
        admin = _get_current_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        return {
            "default_free_credits": 15,
            "stripe_configured": bool(settings.stripe_secret_key),
            "ai_service_configured": False
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_settings(request: Request):
    
    try:
        admin = _get_current_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)

        return {"message": "Settings updated successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def reset_user_password(request: Request, user_id: str):
    
    try:
        admin = _get_current_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        body = await request.json()
        new_password = body.get("new_password")
        
        if not new_password or len(new_password) < 6:
            return JSONResponse({"error": "Password must be at least 6 characters"}, status_code=400)
        
        password_hash = get_password_hash(new_password)
        
        response = supabase.table("users").update({
            "password_hash": password_hash,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", user_id).execute()
        
        if not response.data:
            return JSONResponse({"error": "User not found"}, status_code=404)
        
        return {"message": "Password reset successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
