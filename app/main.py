from fastapi import FastAPI, Request, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import UploadFile, File, Form
from app.core.config import get_settings
from app.controllers import AuthController, ProductController, PlanController, OrderController, PaymentController, GenerationController, AdminController, UserController
from app.controllers import ModelSizeController, FinishOptionController, PaintingTierController, PaintColorController, PricingController, DeliveryController, CustomOrderController
from app.middleware.rate_limiter import RateLimiter, CacheMiddleware
from app.middleware.logging import RequestLoggingMiddleware, TimeoutMiddleware
import os
import uuid
from pathlib import Path

settings = get_settings()

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Noys 3D Prints API",
    description="Backend API for Noys 3D Prints - 3D Printing E-commerce Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

app.add_middleware(TimeoutMiddleware, timeout=30.0)  # Timeout first
app.add_middleware(RateLimiter, calls=100, period=60)  # Rate limiting
app.add_middleware(CacheMiddleware)  # Simple caching
app.add_middleware(RequestLoggingMiddleware)  # Request logging

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.noys3dprints.co.uk",
        "https://noys3dprints.co.uk",
        "https://noys-3-d-prints.vercel.app",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "message": "Welcome to Noys 3D Prints API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    
    import time
    import psutil

    db_status = "healthy"
    db_latency = 0
    try:
        from app.db.connection import get_supabase_client
        supabase = get_supabase_client()
        start = time.time()
        supabase.table("users").select("id").limit(1).execute()
        db_latency = (time.time() - start) * 1000
    except Exception as e:
        db_status = "unhealthy"
        db_latency = 0
    
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "services": {
            "database": {
                "status": db_status,
                "latency_ms": round(db_latency, 2)
            },
            "api": {
                "status": "healthy"
            }
        },
        "system": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent
        }
    }


@app.post("/api/v1/auth/register")
async def register(request: Request):
    return await AuthController.signup(request)


@app.post("/api/v1/auth/login")
async def login(request: Request):
    return await AuthController.login(request)


@app.get("/api/v1/auth/me")
async def get_me(request: Request):
    return await AuthController.get_me(request)


@app.put("/api/v1/auth/me")
async def update_me(request: Request):
    return await AuthController.update_me(request)


@app.post("/api/v1/auth/logout")
async def logout():
    return AuthController.logout()


@app.get("/api/v1/user/profile")
async def get_user_profile(request: Request):
    return await UserController.get_user_profile(request)


@app.put("/api/v1/user/profile")
async def update_user_profile(request: Request):
    return await UserController.update_user_profile(request)


@app.put("/api/v1/user/password")
async def change_password(request: Request):
    return await UserController.change_password(request)


@app.post("/api/v1/contact")
async def submit_contact(request: Request):
    return await UserController.submit_contact(request)


@app.get("/api/v1/categories")
async def list_categories():
    return await ProductController.list_categories()


@app.get("/api/v1/categories/{category_id}")
async def get_category(category_id: str):
    return await ProductController.get_category(category_id)


@app.post("/api/v1/categories")
async def create_category(request: Request):
    return await ProductController.create_category(request)


@app.put("/api/v1/categories/{category_id}")
async def update_category(request: Request, category_id: str):
    return await ProductController.update_category(request, category_id)


@app.delete("/api/v1/categories/{category_id}")
async def delete_category(request: Request, category_id: str):
    return await ProductController.delete_category(request, category_id)


@app.get("/api/v1/products")
async def list_products(request: Request, category: str = None, active_only: bool = True):
    return await ProductController.list_products(category=category, active_only=active_only)


@app.get("/api/v1/products/{product_id}")
async def get_product(product_id: str):
    return await ProductController.get_product(product_id)


@app.post("/api/v1/products")
async def create_product(request: Request):
    return await ProductController.create_product(request)


@app.put("/api/v1/products/{product_id}")
async def update_product(request: Request, product_id: str):
    return await ProductController.update_product(request, product_id)


@app.delete("/api/v1/products/{product_id}")
async def delete_product(request: Request, product_id: str):
    return await ProductController.delete_product(request, product_id)


@app.get("/api/v1/plans")
async def list_plans():
    return await PlanController.list_plans()


@app.get("/api/v1/plans/{plan_id}")
async def get_plan(plan_id: str):
    return await PlanController.get_plan(plan_id)


@app.post("/api/v1/plans")
async def create_plan(request: Request):
    return await PlanController.create_plan(request)


@app.put("/api/v1/plans/{plan_id}")
async def update_plan(request: Request, plan_id: str):
    return await PlanController.update_plan(request, plan_id)


@app.delete("/api/v1/plans/{plan_id}")
async def delete_plan(request: Request, plan_id: str):
    return await PlanController.delete_plan(request, plan_id)


@app.get("/api/v1/credit-packs")
async def list_credit_packs(active_only: bool = True):
    return await PlanController.list_credit_packs(active_only=active_only)


@app.get("/api/v1/credit-packs/{pack_id}")
async def get_credit_pack(pack_id: str):
    return await PlanController.get_credit_pack(pack_id)


@app.post("/api/v1/credit-packs")
async def create_credit_pack(request: Request):
    return await PlanController.create_credit_pack(request)


@app.put("/api/v1/credit-packs/{pack_id}")
async def update_credit_pack(request: Request, pack_id: str):
    return await PlanController.update_credit_pack(request, pack_id)


@app.delete("/api/v1/credit-packs/{pack_id}")
async def delete_credit_pack(request: Request, pack_id: str):
    return await PlanController.delete_credit_pack(request, pack_id)


@app.post("/api/v1/orders")
async def create_order(request: Request):
    return await OrderController.create_order(request)


@app.post("/api/v1/orders/checkout")
async def checkout_order(request: Request):
    return await OrderController.checkout_order(request)


@app.get("/api/v1/orders")
async def list_orders(request: Request):
    return await OrderController.list_orders(request)


@app.get("/api/v1/orders/{order_id}")
async def get_order(request: Request, order_id: str):
    return await OrderController.get_order(request, order_id)


@app.put("/api/v1/orders/{order_id}/status")
async def update_order_status(request: Request, order_id: str):
    return await OrderController.update_order_status(request, order_id)


@app.post("/api/v1/payments/subscribe")
async def subscribe_to_plan(request: Request):
    return await PaymentController.subscribe_to_plan(request)


@app.post("/api/v1/payments/buy-credits")
async def buy_credits(request: Request):
    return await PaymentController.buy_credits(request)


@app.post("/api/v1/payments/checkout")
async def create_checkout_session(request: Request):
    return await PaymentController.create_checkout_session(request)


@app.get("/api/v1/payments/config")
async def get_stripe_config(request: Request):
    return await PaymentController.get_stripe_config(request)


@app.get("/api/v1/payments")
async def list_payments(request: Request):
    return await PaymentController.list_payments(request)


@app.post("/api/v1/payments/webhook")
async def stripe_webhook(request: Request):
    return await PaymentController.stripe_webhook(request)


@app.post("/api/v1/payments/verify-session")
async def verify_session(request: Request):
    return await PaymentController.verify_session(request)


@app.post("/api/v1/generations/generate")
async def generate_model(request: Request, background_tasks: BackgroundTasks):
    return await GenerationController.generate_model(request, background_tasks)


@app.get("/api/v1/generations")
async def list_generations(request: Request, saved_only: bool = False):
    return await GenerationController.list_generations(request, saved_only=saved_only)


@app.get("/api/v1/generations/gallery")
async def get_gallery(request: Request):
    return await GenerationController.get_gallery(request)


@app.get("/api/v1/generations/{generation_id}")
async def get_generation(request: Request, generation_id: str, background_tasks: BackgroundTasks):
    return await GenerationController.get_generation(request, generation_id, background_tasks)


@app.get("/api/v1/generations/{generation_id}/model")
async def get_generation_model(request: Request, generation_id: str):
    """Same-origin proxy for the GLB so the browser viewer can load it
    without hitting Tripo CDN CORS restrictions."""
    return await GenerationController.proxy_model(request, generation_id)


@app.post("/api/v1/generations/{generation_id}/save")
async def save_generation(request: Request, generation_id: str):
    return await GenerationController.save_generation(request, generation_id)


@app.delete("/api/v1/generations/{generation_id}")
async def delete_generation(request: Request, generation_id: str):
    return await GenerationController.delete_generation(request, generation_id)


@app.get("/api/v1/admin/stats")
async def get_stats(request: Request):
    return await AdminController.get_stats(request)


@app.get("/api/v1/admin/users")
async def list_users(request: Request, limit: int = 50, offset: int = 0):
    return await AdminController.list_users(request, limit=limit, offset=offset)


@app.get("/api/v1/admin/users/{user_id}")
async def get_user(request: Request, user_id: str):
    return await AdminController.get_user(request, user_id)


@app.put("/api/v1/admin/users/{user_id}")
async def update_user(request: Request, user_id: str):
    return await AdminController.update_user(request, user_id)


@app.delete("/api/v1/admin/users/{user_id}")
async def delete_user(request: Request, user_id: str):
    return await AdminController.delete_user(request, user_id)


@app.post("/api/v1/admin/users/{user_id}/reset-password")
async def reset_user_password(request: Request, user_id: str):
    return await AdminController.reset_user_password(request, user_id)


@app.get("/api/v1/admin/orders")
async def list_all_orders(request: Request, limit: int = 50, offset: int = 0, status: str = None):
    return await AdminController.list_all_orders(request, limit=limit, offset=offset, status=status)

@app.patch("/api/v1/admin/orders/{order_id}")
async def admin_update_order_status(request: Request, order_id: str):
    return await AdminController.update_order_status(request, order_id)


@app.get("/api/v1/admin/activity")
async def get_recent_activity(request: Request, limit: int = 20):
    return await AdminController.get_recent_activity(request, limit=limit)


@app.get("/api/v1/admin/settings")
async def get_settings(request: Request):
    return await AdminController.get_settings(request)


@app.put("/api/v1/admin/settings")
async def update_settings(request: Request):
    return await AdminController.update_settings(request)


def _supabase_storage_client():
    """Return a Supabase client with service role key for storage operations."""
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_service_key)


@app.post("/api/v1/upload/image")
async def upload_image(file: UploadFile = File(...)):
    try:
        allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
        if file.content_type not in allowed_types:
            return JSONResponse({"error": "Invalid file type. Only JPEG, PNG, WEBP, GIF allowed"}, status_code=400)

        file_ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
        unique_filename = f"{uuid.uuid4()}.{file_ext}"
        content = await file.read()

        # Use Supabase Storage if service key is configured
        if settings.supabase_service_key:
            try:
                sb = _supabase_storage_client()
                sb.storage.from_("uploads").upload(
                    path=unique_filename,
                    file=content,
                    file_options={"content-type": file.content_type, "upsert": "true"},
                )
                public_url = sb.storage.from_("uploads").get_public_url(unique_filename)
                return {"filename": unique_filename, "url": public_url, "content_type": file.content_type, "size": len(content)}
            except Exception as storage_err:
                # Fall through to local storage on error
                import logging
                logging.warning(f"Supabase Storage upload failed, using local: {storage_err}")

        # Local filesystem fallback
        file_path = UPLOAD_DIR / unique_filename
        with open(file_path, "wb") as f:
            f.write(content)
        return {"filename": unique_filename, "url": f"/uploads/{unique_filename}", "content_type": file.content_type, "size": len(content)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# Max video size for product turntable clips. 50 MB is plenty for a short
# 360° loop and keeps Supabase Storage bandwidth reasonable.
PRODUCT_VIDEO_MAX_BYTES = 50 * 1024 * 1024


@app.post("/api/v1/upload/video")
async def upload_video(file: UploadFile = File(...)):
    try:
        allowed_types = ["video/mp4", "video/webm", "video/quicktime", "video/x-m4v"]
        is_allowed_ext = file.filename and file.filename.lower().endswith((".mp4", ".webm", ".mov", ".m4v"))
        if file.content_type not in allowed_types and not is_allowed_ext:
            return JSONResponse({"error": "Invalid file type. Only MP4, WebM, MOV allowed"}, status_code=400)

        content = await file.read()
        if len(content) > PRODUCT_VIDEO_MAX_BYTES:
            return JSONResponse(
                {"error": f"Video too large. Max {PRODUCT_VIDEO_MAX_BYTES // (1024*1024)} MB."},
                status_code=400,
            )

        file_ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "mp4"
        unique_filename = f"vid_{uuid.uuid4()}.{file_ext}"

        if settings.supabase_service_key:
            try:
                sb = _supabase_storage_client()
                sb.storage.from_("uploads").upload(
                    path=unique_filename,
                    file=content,
                    file_options={"content-type": file.content_type or "video/mp4", "upsert": "true"},
                )
                public_url = sb.storage.from_("uploads").get_public_url(unique_filename)
                return {"filename": unique_filename, "url": public_url, "content_type": file.content_type, "size": len(content)}
            except Exception as storage_err:
                import logging
                logging.warning(f"Supabase Storage video upload failed, using local: {storage_err}")

        file_path = UPLOAD_DIR / unique_filename
        with open(file_path, "wb") as f:
            f.write(content)
        return {"filename": unique_filename, "url": f"/uploads/{unique_filename}", "content_type": file.content_type, "size": len(content)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/v1/upload/generation")
async def upload_generation(file: UploadFile = File(...)):
    
    try:

        allowed_types = ["model/stl", "model/obj", "application/octet-stream"]
        if file.content_type not in allowed_types and not file.filename.endswith(('.stl', '.obj')):
            return JSONResponse({"error": "Invalid file type. Only STL and OBJ files allowed"}, status_code=400)

        file_ext = file.filename.split(".")[-1] if "." in file.filename else "stl"
        unique_filename = f"gen_{uuid.uuid4()}.{file_ext}"
        file_path = UPLOAD_DIR / unique_filename

        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        return {
            "filename": unique_filename,
            "url": f"/uploads/{unique_filename}",
            "content_type": file.content_type,
            "size": len(content)
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/uploads/{filename}")
async def get_uploaded_file(filename: str):
    
    from fastapi.responses import FileResponse
    file_path = UPLOAD_DIR / filename
    if file_path.exists():
        return FileResponse(file_path)
    return JSONResponse({"error": "File not found"}, status_code=404)


# ============================================================
# MODEL SIZES
# ============================================================
@app.get("/api/v1/model-sizes")
async def list_model_sizes(active_only: bool = True):
    return await ModelSizeController.list_sizes(active_only=active_only)

@app.get("/api/v1/model-sizes/{size_id}")
async def get_model_size(size_id: str):
    return await ModelSizeController.get_size(size_id)

@app.post("/api/v1/model-sizes")
async def create_model_size(request: Request):
    return await ModelSizeController.create_size(request)

@app.put("/api/v1/model-sizes/{size_id}")
async def update_model_size(request: Request, size_id: str):
    return await ModelSizeController.update_size(request, size_id)

@app.delete("/api/v1/model-sizes/{size_id}")
async def delete_model_size(request: Request, size_id: str):
    return await ModelSizeController.delete_size(request, size_id)


# ============================================================
# FINISH OPTIONS
# ============================================================
@app.get("/api/v1/finish-options")
async def list_finish_options(active_only: bool = True):
    return await FinishOptionController.list_finishes(active_only=active_only)

@app.get("/api/v1/finish-options/{finish_id}")
async def get_finish_option(finish_id: str):
    return await FinishOptionController.get_finish(finish_id)

@app.post("/api/v1/finish-options")
async def create_finish_option(request: Request):
    return await FinishOptionController.create_finish(request)

@app.put("/api/v1/finish-options/{finish_id}")
async def update_finish_option(request: Request, finish_id: str):
    return await FinishOptionController.update_finish(request, finish_id)

@app.delete("/api/v1/finish-options/{finish_id}")
async def delete_finish_option(request: Request, finish_id: str):
    return await FinishOptionController.delete_finish(request, finish_id)


# ============================================================
# PAINTING TIERS
# ============================================================
@app.get("/api/v1/painting-tiers")
async def list_painting_tiers():
    return await PaintingTierController.list_tiers()

@app.get("/api/v1/painting-tiers/{tier_id}")
async def get_painting_tier(tier_id: str):
    return await PaintingTierController.get_tier(tier_id)

@app.get("/api/v1/painting-tiers/for-size/{size_id}")
async def get_painting_tier_for_size(size_id: str):
    return await PaintingTierController.get_tier_for_size(size_id)

@app.post("/api/v1/painting-tiers")
async def create_painting_tier(request: Request):
    return await PaintingTierController.create_tier(request)

@app.put("/api/v1/painting-tiers/{tier_id}")
async def update_painting_tier(request: Request, tier_id: str):
    return await PaintingTierController.update_tier(request, tier_id)

@app.delete("/api/v1/painting-tiers/{tier_id}")
async def delete_painting_tier(request: Request, tier_id: str):
    return await PaintingTierController.delete_tier(request, tier_id)

@app.put("/api/v1/painting-tiers/{tier_id}/mappings")
async def update_tier_size_mappings(request: Request, tier_id: str):
    return await PaintingTierController.update_size_mappings(request, tier_id)

@app.put("/api/v1/painting-tiers/{tier_id}/sizes/{size_id}/override")
async def set_painting_price_override(request: Request, tier_id: str, size_id: str):
    return await PaintingTierController.set_size_price_override(request, tier_id, size_id)


# ============================================================
# PAINT COLORS
# ============================================================
@app.get("/api/v1/paint-colors")
async def list_paint_colors(active_only: bool = True):
    return await PaintColorController.list_colors(active_only=active_only)

@app.get("/api/v1/paint-colors/{color_id}")
async def get_paint_color(color_id: str):
    return await PaintColorController.get_color(color_id)

@app.post("/api/v1/paint-colors")
async def create_paint_color(request: Request):
    return await PaintColorController.create_color(request)

@app.put("/api/v1/paint-colors/{color_id}")
async def update_paint_color(request: Request, color_id: str):
    return await PaintColorController.update_color(request, color_id)

@app.delete("/api/v1/paint-colors/{color_id}")
async def delete_paint_color(request: Request, color_id: str):
    return await PaintColorController.delete_color(request, color_id)


# ============================================================
# PRICING ENGINE
# ============================================================
@app.post("/api/v1/pricing/calculate")
async def calculate_price(request: Request):
    return await PricingController.calculate_price(request)


# ============================================================
# DELIVERY SETTINGS
# ============================================================
@app.get("/api/v1/delivery-settings")
async def get_delivery_settings_route():
    return await DeliveryController.get_delivery_settings()

@app.put("/api/v1/delivery-settings")
async def update_delivery_settings_route(request: Request):
    return await DeliveryController.update_delivery_settings(request)


# ============================================================
# CUSTOM ORDERS (with approval workflow)
# ============================================================
@app.post("/api/v1/custom-orders/checkout")
async def initiate_custom_order_checkout(request: Request):
    return await CustomOrderController.initiate_checkout(request)

@app.post("/api/v1/custom-orders")
async def create_custom_order(request: Request):
    return await CustomOrderController.create_custom_order(request)

@app.get("/api/v1/custom-orders")
async def list_custom_orders(request: Request):
    return await CustomOrderController.list_custom_orders(request)

@app.get("/api/v1/custom-orders/{order_id}")
async def get_custom_order(request: Request, order_id: str):
    return await CustomOrderController.get_custom_order(request, order_id)

@app.get("/api/v1/admin/custom-orders")
async def admin_list_custom_orders(request: Request, limit: int = 50, offset: int = 0, status: str = None):
    return await CustomOrderController.admin_list_custom_orders(request, limit=limit, offset=offset, status=status)

@app.put("/api/v1/admin/custom-orders/{order_id}/status")
async def update_custom_order_status(request: Request, order_id: str):
    return await CustomOrderController.update_order_status(request, order_id)

@app.put("/api/v1/admin/custom-orders/{order_id}/review")
async def review_custom_order(request: Request, order_id: str):
    return await CustomOrderController.review_order(request, order_id)

@app.post("/api/v1/admin/custom-orders/{order_id}/notes")
async def add_custom_order_note(request: Request, order_id: str):
    return await CustomOrderController.add_order_note(request, order_id)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
