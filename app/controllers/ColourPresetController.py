from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.security import decode_access_token
from datetime import datetime
from uuid import uuid4
from typing import Optional


supabase = get_supabase_client()


def _require_admin(request: Request) -> Optional[dict]:
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
    return user if user.get("role") == "admin" else None


async def list_presets():
    try:
        rows = (
            supabase.table("colour_presets")
            .select("*")
            .order("sort_order")
            .order("name")
            .execute()
        )
        return rows.data or []
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def create_preset(request: Request):
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        body = await request.json()
        name = (body.get("name") or "").strip()
        hex_code = (body.get("hex_code") or "").strip()
        if not name or not hex_code:
            return JSONResponse({"error": "name and hex_code are required"}, status_code=400)
        row = {
            "id": str(uuid4()),
            "name": name,
            "hex_code": hex_code,
            "sort_order": int(body.get("sort_order") or 0),
            "created_at": datetime.utcnow().isoformat(),
        }
        result = supabase.table("colour_presets").insert(row).execute()
        return result.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_preset(request: Request, preset_id: str):
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        body = await request.json()
        update: dict = {}
        if "name" in body:
            update["name"] = (body["name"] or "").strip()
        if "hex_code" in body:
            update["hex_code"] = (body["hex_code"] or "").strip()
        if "sort_order" in body:
            update["sort_order"] = int(body["sort_order"] or 0)
        if not update:
            return JSONResponse({"error": "Nothing to update"}, status_code=400)
        result = supabase.table("colour_presets").update(update).eq("id", preset_id).execute()
        if not result.data:
            return JSONResponse({"error": "Preset not found"}, status_code=404)
        return result.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_preset(request: Request, preset_id: str):
    try:
        admin = _require_admin(request)
        if not admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        result = supabase.table("colour_presets").delete().eq("id", preset_id).execute()
        if not result.data:
            return JSONResponse({"error": "Preset not found"}, status_code=404)
        return {"message": "Preset deleted"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
