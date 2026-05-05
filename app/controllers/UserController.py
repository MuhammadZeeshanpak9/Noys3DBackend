from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.security import decode_access_token, get_password_hash, verify_password
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


async def submit_contact(request: Request):
    
    try:
        body = await request.json()
        name = body.get("name")
        email = body.get("email")
        message = body.get("message")
        
        if not name or not email or not message:
            return JSONResponse({"error": "Name, email, and message are required"}, status_code=400)

        from app.utils.email import send_contact_message
        import asyncio
        asyncio.create_task(send_contact_message(name, email, message))

        return {"message": "Thank you for your message! We'll get back to you soon."}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def change_password(request: Request):
    
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        
        body = await request.json()
        current_password = body.get("current_password")
        new_password = body.get("new_password")
        
        if not current_password or not new_password:
            return JSONResponse({"error": "Current and new password are required"}, status_code=400)

        user_response = supabase.table("users").select("password_hash").eq("id", current_user["id"]).execute()
        if not user_response.data:
            return JSONResponse({"error": "User not found"}, status_code=404)
        
        stored_hash = user_response.data[0]["password_hash"]
        
        if not verify_password(current_password, stored_hash):
            return JSONResponse({"error": "Current password is incorrect"}, status_code=400)

        new_hash = get_password_hash(new_password)
        
        supabase.table("users").update({
            "password_hash": new_hash,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", current_user["id"]).execute()
        
        return {"message": "Password updated successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_user_profile(request: Request):
    
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        
        return {
            "id": current_user["id"],
            "email": current_user["email"],
            "name": current_user["name"],
            "role": current_user["role"],
            "credits": current_user.get("credits", 0),
            "subscription_plan": current_user.get("subscription_plan", "starter"),
            "avatar_url": current_user.get("avatar_url"),
            "shipping_address": current_user.get("shipping_address", {}),
            "created_at": current_user["created_at"]
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_user_profile(request: Request):
    
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        
        body = await request.json()
        # SECURITY: Only allow updating safe fields — prevent privilege escalation
        allowed_fields = ["name", "avatar_url", "shipping_address", "phone"]
        update_data = {k: v for k, v in body.items() if k in allowed_fields and v is not None}
        update_data["updated_at"] = datetime.utcnow().isoformat()
        
        response = supabase.table("users").update(update_data).eq("id", current_user["id"]).execute()
        
        if not response.data:
            return JSONResponse({"error": "Failed to update profile"}, status_code=400)
        
        return response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
