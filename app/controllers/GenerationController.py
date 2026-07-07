from fastapi import Request, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse, Response
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

# Tripo model versions are date-stamped enum strings — a bare "v3.0" is rejected
# by the /task endpoint. Valid values include v2.5-20250123 (old default),
# v3.0-20250812, v3.1-20260211. Kept as one constant so it's a single place to
# bump or revert. If generation ever breaks on a version, fall back to
# "v2.5-20250123" which is the known-good default.
TRIPO_MODEL_VERSION = "v3.0-20250812"

# Maps generation_id → tripo task_id for in-progress generations.
_active_tasks: dict = {}
# Maps generation_id → last known Tripo progress (0-100).
_task_progress: dict = {}
# Guards against concurrent finalize (download+upload) of the same generation.
_finalizing: set = set()

# Prompt suffixes — short and focused on what Tripo's parser can act on.
# Grey colour is enforced at the frontend by ModelViewer3DInner.GREY_MATERIAL,
# so we no longer ask Tripo for grey (that confused its texture-synth pass).
STYLE_SUFFIX = (
    ", highly detailed 3D sculpt, sharp edge definition, "
    "clean topology, fine surface relief, natural proportions, "
    "hero asset level of detail, single isolated object, strong silhouette"
)

IMAGE_STYLE_SUFFIX = (
    "Reconstruct as a highly detailed 3D sculpt with sharp edges, "
    "clean topology, and fine surface relief. Single isolated object."
)

# Keywords that signal a person/character subject — when matched, we pass
# Tripo's `person:person2cartoon` style preset which produces the caricature
# figurine look in the client's reference images.
PERSON_KEYWORDS = {
    "person", "people", "man", "woman", "boy", "girl", "child", "kid",
    "character", "hero", "figure", "miniature", "human", "lady", "guy",
    "knight", "soldier", "wizard", "warrior", "king", "queen", "prince",
    "princess", "elf", "dwarf", "orc", "monk", "ninja", "samurai",
    "guard", "fairy", "angel", "demon", "father", "mother", "son",
    "daughter", "doctor", "nurse", "officer", "chef", "pilot",
    "athlete", "dancer", "worker", "gallerist", "portrait", "bust",
}


def _detect_person_subject(prompt: str, has_image: bool) -> bool:
    """Apply the person-cartoon style only when the prompt text actually names a
    person. Previously this returned True for ANY image-only upload, which wrongly
    forced the person2cartoon preset onto photos of vehicles, buildings and
    objects — producing cartoon characters instead of a faithful model."""
    if not prompt:
        return False
    lower = prompt.lower()
    return any(kw in lower for kw in PERSON_KEYWORDS)


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


async def _submit_tripo_task(api_key: str, prompt: str = "", file_token: str = None, file_ext: str = "jpeg") -> Optional[str]:
    """Submit a generation task to Tripo, returns task_id or None on failure."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    has_image = bool(file_token)
    is_person = _detect_person_subject(prompt, has_image)

    # Quality params shared by both pathways. We keep texture: False because
    # PBR-textured GLBs from Tripo can reference external texture files that
    # the proxy_model endpoint doesn't stream, causing useGLTF to fail load.
    # Grey display is enforced at view time by the frontend GREY_MATERIAL
    # override (ModelViewer3DInner.tsx) — no texture needed.
    # quad: True was tried for cleaner topology but produced GLBs that
    # three.js GLTFLoader couldn't parse — stick with default triangulation.
    quality_params = {
        "texture": False,
        "face_limit": 30000,
    }

    if has_image:
        tripo_type = "png" if file_ext in ("png",) else "jpeg"
        payload = {
            "type": "image_to_model",
            "model_version": TRIPO_MODEL_VERSION,
            "file": {"type": tripo_type, "file_token": file_token},
            "prompt": IMAGE_STYLE_SUFFIX,
            **quality_params,
        }
    else:
        payload = {
            "type": "text_to_model",
            "model_version": TRIPO_MODEL_VERSION,
            "prompt": prompt + STYLE_SUFFIX,
            **quality_params,
        }

    if is_person:
        payload["style"] = "person:person2cartoon"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{TRIPO_API_BASE}/task", headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["data"]["task_id"]
    except Exception as e:
        logger.error(f"Tripo task submit failed: {e}")
        return None


_IMAGE_EXT_BY_TYPE = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


async def _persist_asset(generation_id: str, url: str, kind: str) -> Optional[str]:
    """Download a temporary Tripo asset and store it permanently in Supabase
    Storage. Tripo's CDN URLs expire (~24h); persisting here is what stops the
    'preview has expired' failure. Returns the permanent public URL or None.

    kind="model" → forced .glb / model-gltf-binary (Tripo's CDN often mislabels
    the GLB content-type). kind="image" → use the real content-type from the
    response so the stored thumbnail's extension/type match the actual bytes."""
    try:
        from supabase import create_client
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.content
            resp_ct = r.headers.get("content-type", "").split(";")[0].strip().lower()

        if kind == "model":
            ext, content_type = "glb", "model/gltf-binary"
        else:
            ext = _IMAGE_EXT_BY_TYPE.get(resp_ct, "png")
            content_type = resp_ct if resp_ct in _IMAGE_EXT_BY_TYPE else "image/png"

        sb = create_client(settings.supabase_url, settings.supabase_service_key)
        path = f"generations/{generation_id}.{ext}"
        sb.storage.from_("uploads").upload(
            path=path,
            file=data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        return sb.storage.from_("uploads").get_public_url(path)
    except Exception as e:
        logger.error(f"Persist {kind} failed for {generation_id}: {e}")
        return None


async def _finalize_success(generation_id: str, output: dict):
    """Resolve Tripo output, persist the GLB + preview image to Supabase so the
    stored URLs never expire, then update the DB row. Idempotent and guarded
    against concurrent runs."""
    if generation_id in _finalizing:
        return
    _finalizing.add(generation_id)
    try:
        # 2D preview image — base_model is a GLB, NOT an image.
        rendered = (
            output.get("rendered_image") or
            output.get("generated_image") or
            output.get("model_thumbnail") or
            output.get("thumbnail")
        )
        # 3D model URL. With texture: false Tripo returns the GLB under
        # base_model, so it MUST be included here.
        model_url = (
            output.get("model") or
            output.get("base_model") or
            output.get("pbr_model") or
            output.get("glb_model")
        )

        perm_model = await _persist_asset(generation_id, model_url, "model") if model_url else None
        perm_img = await _persist_asset(generation_id, rendered, "image") if rendered else None

        final_stl = perm_model or model_url
        # image_url must be non-null so the frontend knows generation succeeded.
        final_image = perm_img or rendered or final_stl or ""

        supabase.table("generations").update({
            "image_url": final_image,
            "stl_url": final_stl,
        }).eq("id", generation_id).execute()
        _active_tasks.pop(generation_id, None)
        _task_progress.pop(generation_id, None)
        logger.info(f"Generation {generation_id} finalized — image={bool(perm_img or rendered)} model={bool(final_stl)}")
    finally:
        _finalizing.discard(generation_id)


async def _mark_failed_and_refund(generation_id: str, user_id: Optional[str]):
    """Mark a generation as failed (image_url='' is the failure sentinel the
    frontend reads) and refund the credit that was charged up-front."""
    supabase.table("generations").update({"image_url": ""}).eq("id", generation_id).execute()
    _active_tasks.pop(generation_id, None)
    _task_progress.pop(generation_id, None)
    if user_id:
        await _refund_credit(user_id)


async def _refund_credit(user_id: str):
    """Give back 1 credit on definitive failure/timeout so users are never
    charged for a generation that didn't produce a model."""
    try:
        rows = supabase.table("users").select("credits").eq("id", user_id).execute().data
        if not rows:
            return
        current = rows[0].get("credits") or 0
        supabase.table("users").update({
            "credits": current + 1,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", user_id).execute()
        logger.info(f"Refunded 1 credit to {user_id} after failed generation")
    except Exception as e:
        logger.error(f"Credit refund failed for {user_id}: {e}")


async def _poll_and_update(generation_id: str, task_id: str, api_key: str, user_id: Optional[str] = None):
    """Background task: polls Tripo every 5s until success/failure, then persists
    assets to Supabase (success) or refunds the credit (failure/timeout)."""
    headers = {"Authorization": f"Bearer {api_key}"}

    for _ in range(120):  # ~10 minutes max
        await asyncio.sleep(5)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{TRIPO_API_BASE}/task/{task_id}", headers=headers)
                data = resp.json().get("data", {})
                status = data.get("status")
                _task_progress[generation_id] = data.get("progress", _task_progress.get(generation_id, 0))

                if status == "success":
                    output = data.get("output", {})
                    logger.info(f"Tripo output keys for {generation_id}: {list(output.keys())}")
                    await _finalize_success(generation_id, output)
                    return

                if status == "failed":
                    logger.warning(f"Tripo task {task_id} failed")
                    await _mark_failed_and_refund(generation_id, user_id)
                    return

        except Exception as e:
            logger.error(f"Tripo poll error: {e}")
            continue

    # Timed out — mark as failed and refund
    logger.warning(f"Tripo task {task_id} timed out")
    await _mark_failed_and_refund(generation_id, user_id)


async def _run_generation(generation_id: str, user_id: str, prompt: str,
                          image_bytes: Optional[bytes], filename: Optional[str],
                          file_ext: str, api_key: str):
    """Full generation lifecycle, run in the background so the HTTP request that
    started it returns immediately and never hits the 30s request timeout:
    upload reference image (if any) → submit Tripo task → persist task_id →
    poll → finalize (persist assets) or refund on failure."""
    try:
        file_token = None
        if image_bytes:
            file_token = await _upload_image_to_tripo(api_key, image_bytes, filename or "upload.jpg")
            if not file_token:
                logger.warning(f"Image upload to Tripo failed for {generation_id}")
                await _mark_failed_and_refund(generation_id, user_id)
                return

        task_id = await _submit_tripo_task(api_key, prompt=prompt, file_token=file_token, file_ext=file_ext)
        if not task_id:
            logger.warning(f"Tripo task submit returned no id for {generation_id}")
            await _mark_failed_and_refund(generation_id, user_id)
            return

        # Persist the task_id so polling can resume after a Railway restart that
        # would otherwise wipe the in-memory _active_tasks map.
        supabase.table("generations").update({"tripo_task_id": task_id}).eq("id", generation_id).execute()
        _active_tasks[generation_id] = task_id

        await _poll_and_update(generation_id, task_id, api_key, user_id)
    except Exception as e:
        logger.error(f"_run_generation error for {generation_id}: {e}")
        await _mark_failed_and_refund(generation_id, user_id)


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

        if not settings.tripo_api_key:
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

        # Read the uploaded image bytes now — the UploadFile is bound to this
        # request and won't be readable inside the background task.
        image_bytes = None
        filename = None
        file_ext = "jpeg"
        if image_files:
            img = image_files[0]
            image_bytes = await img.read()
            filename = img.filename or "upload.jpg"
            file_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpeg"

        # Save a pending record (image_url=None → frontend knows it's processing).
        generation = {
            "id": generation_id,
            "user_id": current_user["id"],
            "prompt": prompt or "(image reference)",
            "image_url": None,
            "stl_url": None,
            "is_saved": False,
            "credits_used": 1,
            "tripo_task_id": None,
            "created_at": datetime.utcnow().isoformat(),
        }
        supabase.table("generations").insert(generation).execute()

        # Deduct the credit up-front (refunded automatically if generation fails).
        supabase.table("users").update({
            "credits": user_credits - 1,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", current_user["id"]).execute()

        # Hand all Tripo work to the background — endpoint returns immediately.
        background_tasks.add_task(
            _run_generation, generation_id, current_user["id"], prompt,
            image_bytes, filename, file_ext, settings.tripo_api_key,
        )

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


async def get_generation(request: Request, generation_id: str, background_tasks: BackgroundTasks):
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

        # Resume tracking after a Railway restart: if this generation is still
        # pending but we've lost the in-memory task handle, recover it from the
        # persisted tripo_task_id so the on-demand check below can drive it.
        if generation.get("image_url") is None and generation_id not in _active_tasks:
            task_id_db = generation.get("tripo_task_id")
            if task_id_db and settings.tripo_api_key:
                _active_tasks[generation_id] = task_id_db

        # On-demand Tripo check: if still processing and we have the task_id, ask
        # Tripo now. This makes each frontend poll actively drive progress rather
        # than waiting only for the background task (which a Railway restart can
        # kill). Heavy asset persistence is scheduled in the background so this
        # GET stays well under the 30s request timeout.
        if generation.get("image_url") is None and generation_id in _active_tasks and settings.tripo_api_key:
            task_id = _active_tasks[generation_id]
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"{TRIPO_API_BASE}/task/{task_id}",
                        headers={"Authorization": f"Bearer {settings.tripo_api_key}"},
                    )
                    data = resp.json().get("data", {})
                    status = data.get("status")
                    progress = data.get("progress", 0)
                    _task_progress[generation_id] = progress
                    logger.info(f"On-demand Tripo check for {generation_id}: status={status} progress={progress}")

                    if status == "success":
                        output = data.get("output", {})
                        logger.info(f"On-demand Tripo output keys for {generation_id}: {list(output.keys())}")
                        # Persist in the background (download+upload can exceed the
                        # request timeout). This poll keeps returning 'processing';
                        # the next poll returns the permanent URLs.
                        background_tasks.add_task(_finalize_success, generation_id, output)
                    elif status == "failed":
                        await _mark_failed_and_refund(generation_id, generation.get("user_id"))
                        generation["image_url"] = ""
            except Exception as e:
                logger.error(f"On-demand Tripo check failed for {generation_id}: {e}")

        # Attach live progress so frontend can show a real progress bar
        generation["processing_progress"] = _task_progress.get(generation_id, 0)
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


async def proxy_model(request: Request, generation_id: str):
    """Stream the GLB model from storage through our backend so the browser sees
    it as same-origin. Now that models are persisted to Supabase Storage the
    upstream URL is permanent (no more expiry), but we keep the proxy so the
    frontend viewer needs no changes.

    We use true streaming (not buffer-then-return) so large GLBs (cars,
    detailed models) don't exhaust memory and don't take so long to first
    byte that an upstream timeout middleware kills the connection.

    No auth here — useGLTF can't send an Authorization header, and the
    generation_id is a UUIDv4 (effectively unguessable) so the URL itself
    is the access token. The model file isn't sensitive PII."""
    try:
        # Look up the generation.
        row = supabase.table("generations").select("stl_url").eq("id", generation_id).execute()
        if not row.data:
            return JSONResponse({"error": "Generation not found"}, status_code=404)

        gen_row = row.data[0]
        upstream_url = gen_row.get("stl_url")
        if not upstream_url:
            return JSONResponse({"error": "No 3D model available for this generation"}, status_code=404)

        logger.info(f"proxy_model fetching upstream for {generation_id}: {upstream_url[:120]}")

        # Open a long-lived client and stream. The client closes inside the
        # generator after the last chunk is yielded.
        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=15.0), follow_redirects=True)
        try:
            req = client.build_request("GET", upstream_url)
            upstream = await client.send(req, stream=True)
        except Exception as fetch_err:
            await client.aclose()
            logger.error(f"Upstream connect failed for {generation_id}: {fetch_err}")
            return JSONResponse({"error": "Could not reach upstream model host"}, status_code=502)

        if upstream.status_code != 200:
            await upstream.aclose()
            await client.aclose()
            logger.warning(f"Upstream model fetch failed for {generation_id}: HTTP {upstream.status_code}")
            return JSONResponse(
                {"error": f"Upstream returned HTTP {upstream.status_code}"},
                status_code=502,
            )

        content_type = upstream.headers.get("content-type", "model/gltf-binary")
        content_length = upstream.headers.get("content-length")

        async def gen():
            try:
                async for chunk in upstream.aiter_bytes(chunk_size=64 * 1024):
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        headers = {
            "Cache-Control": "public, max-age=31536000, immutable",
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
        }
        if content_length:
            headers["Content-Length"] = content_length

        return StreamingResponse(gen(), media_type=content_type, headers=headers)
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching model for {generation_id}")
        return JSONResponse({"error": "Upstream timed out"}, status_code=504)
    except Exception as e:
        logger.error(f"proxy_model error for {generation_id}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
