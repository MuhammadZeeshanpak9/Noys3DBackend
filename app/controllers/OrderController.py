from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.security import decode_access_token
from app.core.config import get_settings
from datetime import datetime
from uuid import uuid4
from typing import Optional
import stripe as stripe_lib


supabase = get_supabase_client()
settings = get_settings()

if settings.stripe_secret_key:
    # .strip() — same defensive guard as the other payment controllers;
    # trailing newlines pasted into a hosting dashboard corrupt the API key.
    stripe_lib.api_key = settings.stripe_secret_key.strip()


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


def _validate_items_total(items: list):
    """Server-side price validation — never trust client-provided prices.
    Returns (total, validated_items) or raises ValueError with a message.
    """
    total = 0.0
    validated = []
    for item in items:
        product_id = item.get("id") or item.get("product_id")
        qty = max(1, int(item.get("quantity", 1)))
        name = item.get("name", "Item")
        if product_id:
            prod_resp = supabase.table("products").select("name, price").eq("id", product_id).execute()
            if not prod_resp.data:
                raise ValueError(f"Product not found: {product_id}")
            unit_price = float(prod_resp.data[0]["price"])
            name = prod_resp.data[0].get("name") or name
        else:
            unit_price = float(item.get("price", 0))
        total += unit_price * qty
        validated.append({
            "id": product_id,
            "name": name,
            "price": unit_price,
            "quantity": qty,
            "image": item.get("image"),
        })
    return round(total, 2), validated


async def create_order(request: Request):
    # Deprecated: this path created an order WITHOUT taking payment, which
    # allowed "free" orders. The customer checkout now goes through
    # checkout_order() (real Stripe). Kept only to return a clear error.
    return JSONResponse(
        {"error": "This endpoint is no longer available. Use /orders/checkout to place an order."},
        status_code=410,
    )


async def checkout_order(request: Request):
    """Create a shop order + real Stripe Checkout Session.
    Mirrors CustomOrderController.initiate_checkout. The order is stored as
    `awaiting_payment` and only flipped to `processing` by the Stripe webhook
    (or verify-session) once payment actually completes."""
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        body = await request.json()
        items = body.get("items", [])
        shipping_address = body.get("shipping_address")

        if not items or not shipping_address:
            return JSONResponse({"error": "Items and shipping address are required"}, status_code=400)

        try:
            total, validated_items = _validate_items_total(items)
        except ValueError as ve:
            return JSONResponse({"error": str(ve)}, status_code=400)

        if total <= 0:
            return JSONResponse({"error": "Order total must be greater than zero"}, status_code=400)

        order_id = str(uuid4())
        order = {
            "id": order_id,
            "user_id": current_user["id"],
            "items": validated_items,
            "total": total,
            "status": "awaiting_payment",
            "shipping_address": shipping_address,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        supabase.table("orders").insert(order).execute()

        # ── Stripe checkout session ───────────────────────────────────────────
        if settings.stripe_secret_key:
            try:
                line_items = [{
                    "price_data": {
                        "currency": "gbp",
                        "product_data": {"name": it["name"]},
                        "unit_amount": int(round(it["price"] * 100)),
                    },
                    "quantity": it["quantity"],
                } for it in validated_items]

                session = stripe_lib.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=line_items,
                    mode="payment",
                    success_url=f"{settings.frontend_url}/orders/success?session_id={{CHECKOUT_SESSION_ID}}&order_id={order_id}&kind=shop",
                    cancel_url=f"{settings.frontend_url}/checkout?cancelled=true",
                    customer_email=current_user.get("email"),
                    metadata={"order_id": order_id, "user_id": current_user["id"], "type": "shop_order"},
                )
                return {"checkout_url": session.url, "order_id": order_id}
            except Exception as stripe_err:
                # Clean up the awaiting_payment order on Stripe error
                supabase.table("orders").delete().eq("id", order_id).execute()
                return JSONResponse({"error": f"Payment setup failed: {str(stripe_err)}"}, status_code=500)

        # Stripe not configured — activate immediately (dev/test mode only)
        supabase.table("orders").update({"status": "processing"}).eq("id", order_id).execute()
        try:
            from app.utils.email import send_shop_order_confirmation, send_admin_shop_order
            import asyncio
            summary = ", ".join(f"{it['quantity']}x {it['name']}" for it in validated_items)
            asyncio.create_task(send_shop_order_confirmation(current_user["email"], order_id, total, summary))
            asyncio.create_task(send_admin_shop_order(order_id, current_user["email"], total, summary))
        except Exception:
            pass
        return {"checkout_url": None, "order_id": order_id}
    except Exception as e:
        import logging
        logging.error(f"checkout_order error: {e}")
        return JSONResponse({"error": "Failed to start checkout"}, status_code=500)


async def list_orders(request: Request):
    
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        
        response = supabase.table("orders").select("*").eq("user_id", current_user["id"]).order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        import logging
        logging.error(f"list_orders error: {e}")
        return JSONResponse({"error": "Failed to list orders"}, status_code=500)


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
        import logging
        logging.error(f"get_order error: {e}")
        return JSONResponse({"error": "Failed to get order"}, status_code=500)


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
        import logging
        logging.error(f"update_order_status error: {e}")
        return JSONResponse({"error": "Failed to update order status"}, status_code=500)
