from fastapi import Request, BackgroundTasks
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.security import decode_access_token
from app.core.config import get_settings
from datetime import datetime
from uuid import uuid4
from typing import Optional
import asyncio
import httpx
import logging

logger = logging.getLogger(__name__)

supabase = get_supabase_client()
settings = get_settings()

TRIPO_API_BASE = "https://api.tripo3d.ai/v2/openapi"


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


async def _upload_image_to_tripo(api_key: str, file_bytes: bytes, filename: str) -> Optional[str]:
    """Upload image to Tripo, returns file_token or None on failure."""
    headers = {"Authorization": f"Bearer {api_key}"}
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpeg"
    mime = f"image/{ext}" if ext in ("jpeg", "jpg", "png", "webp") else "image/jpeg"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{TRIPO_API_BASE}/upload",
                headers=headers,
                files={"file": (filename, file_bytes, mime)},
            )
            resp.raise_for_status()
            return resp.json()["data"]["image_token"]
    except Exception as e:
        logger.error(f"Tripo upload failed: {e}")
        return None


async def _submit_tripo_task(api_key: str, prompt: str = "", file_token: str = None) -> Optional[str]:
    """Submit a generation task to Tripo, returns task_id or None on failure."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    if file_token:
        payload = {
            "type": "image_to_model",
            "file": {"type": "jpeg", "file_token": file_token},
        }
    else:
        payload = {
            "type": "text_to_model",
            "prompt": prompt,
        }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{TRIPO_API_BASE}/task", headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["data"]["task_id"]
    except Exception as e:
        logger.error(f"Tripo task submit failed: {e}")
        return None


async def _poll_and_update(generation_id: str, task_id: str, api_key: str):
    """Background task: polls Tripo every 5s until success/failure, then updates DB."""
    headers = {"Authorization": f"Bearer {api_key}"}

    for _ in range(48):  # ~4 minutes max
        await asyncio.sleep(5)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{TRIPO_API_BASE}/task/{task_id}", headers=headers)
                data = resp.json().get("data", {})
                status = data.get("status")

                if status == "success":
                    output = data.get("output", {})
                    rendered_image = output.get("rendered_image") or output.get("base_model")
                    model_url = output.get("model") or output.get("pbr_model")
                    supabase.table("generations").update({
                        "image_url": rendered_image or "",
                        "stl_url": model_url,
                    }).eq("id", generation_id).execute()
                    logger.info(f"Generation {generation_id} completed via Tripo")
                    return

                if status == "failed":
                    supabase.table("generations").update({"image_url": ""}).eq("id", generation_id).execute()
                    logger.warning(f"Tripo task {task_id} failed")
                    return

        except Exception as e:
            logger.error(f"Tripo poll error: {e}")
            continue

    # Timed out — mark as failed
    supabase.table("generations").update({"image_url": ""}).eq("id", generation_id).execute()
    logger.warning(f"Tripo task {task_id} timed out")


async def generate_model(request: Request, background_tasks: BackgroundTasks):
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        user_credits = current_user.get("credits", 0)
        if user_credits < 1:
            return JSONResponse({"error": "Insufficient credits. Please purchase more credits."}, status_code=402)

        form = await request.form()
        prompt = form.get("prompt", "")
        image_files = form.getlist("images")

        generation_id = str(uuid4())

        if settings.tripo_api_key:
            file_token = None

            # Upload first image to Tripo if provided
            if image_files:
                img = image_files[0]
                file_bytes = await img.read()
                file_token = await _upload_image_to_tripo(settings.tripo_api_key, file_bytes, img.filename or "upload.jpg")

            # Submit task (image or text)
            task_id = await _submit_tripo_task(settings.tripo_api_key, prompt=prompt, file_token=file_token)

            if not task_id:
                return JSONResponse({"error": "Failed to submit generation task. Please try again."}, status_code=500)

            # Save record with null image_url → frontend knows it's still processing
            generation = {
                "id": generation_id,
                "user_id": current_user["id"],
                "prompt": prompt or "(image reference)",
                "image_url": None,
                "stl_url": None,
                "is_saved": False,
                "credits_used": 1,
                "created_at": datetime.utcnow().isoformat(),
            }
            supabase.table("generations").insert(generation).execute()

            # Deduct credit immediately
            supabase.table("users").update({
                "credits": user_credits - 1,
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", current_user["id"]).execute()

            # Poll Tripo in background and update DB when done
            background_tasks.add_task(_poll_and_update, generation_id, task_id, settings.tripo_api_key)

            return supabase.table("generations").select("*").eq("id", generation_id).execute().data[0]

        else:
            # Tripo not configured — return placeholder so UI still works
            generation = {
                "id": generation_id,
                "user_id": current_user["id"],
                "prompt": prompt or "(image reference)",
                "image_url": "https://placehold.co/600x400?text=3D+Preview",
                "stl_url": None,
                "is_saved": False,
                "credits_used": 1,
                "created_at": datetime.utcnow().isoformat(),
            }
            supabase.table("users").update({
                "credits": user_credits - 1,
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", current_user["id"]).execute()
            supabase.table("generations").insert(generation).execute()
            return supabase.table("generations").select("*").eq("id", generation_id).execute().data[0]

    except Exception as e:
        logger.error(f"generate_model error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def list_generations(request: Request, saved_only: bool = False):
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        query = supabase.table("generations").select("*").eq("user_id", current_user["id"])
        if saved_only:
            query = query.eq("is_saved", True)
        response = query.order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_generation(request: Request, generation_id: str):
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        response = supabase.table("generations").select("*").eq("id", generation_id).execute()
        if not response.data:
            return JSONResponse({"error": "Generation not found"}, status_code=404)
        generation = response.data[0]
        if generation["user_id"] != current_user["id"] and current_user.get("role") != "admin":
            return JSONResponse({"error": "Access denied"}, status_code=403)
        return generation
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def save_generation(request: Request, generation_id: str):
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        response = supabase.table("generations").select("*").eq("id", generation_id).execute()
        if not response.data:
            return JSONResponse({"error": "Generation not found"}, status_code=404)
        generation = response.data[0]
        if generation["user_id"] != current_user["id"]:
            return JSONResponse({"error": "Access denied"}, status_code=403)
        update_response = supabase.table("generations").update({"is_saved": True}).eq("id", generation_id).execute()
        return update_response.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_generation(request: Request, generation_id: str):
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        response = supabase.table("generations").select("*").eq("id", generation_id).execute()
        if not response.data:
            return JSONResponse({"error": "Generation not found"}, status_code=404)
        generation = response.data[0]
        if generation["user_id"] != current_user["id"] and current_user.get("role") != "admin":
            return JSONResponse({"error": "Access denied"}, status_code=403)
        supabase.table("generations").delete().eq("id", generation_id).execute()
        return {"message": "Generation deleted successfully"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_gallery(request: Request):
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        response = supabase.table("generations").select("*").eq("user_id", current_user["id"]).eq("is_saved", True).order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        logger.error(f"Gallery error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)
