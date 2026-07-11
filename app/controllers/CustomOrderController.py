"""
Custom Order Controller — Handles custom model orders with approval workflow.
Statuses: new_order → in_review → approved → printing → kit_packing/painting → completed → shipped
Review: pending → approved / changes_requested / rejected
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.auth_utils import get_current_user, require_admin, auth_error_response, admin_error_response
from app.core.config import get_settings
from datetime import datetime
from uuid import uuid4
import stripe as stripe_lib
import json

supabase = get_supabase_client()
settings = get_settings()

if settings.stripe_secret_key:
    # .strip() — same defensive guard as PaymentController; trailing
    # newlines from hosting dashboards corrupt the Authorization header.
    stripe_lib.api_key = settings.stripe_secret_key.strip()

VALID_STATUSES = ["new_order", "awaiting_payment", "in_review", "printing", "kit_packing", "painting", "completed", "shipped", "cancelled"]
VALID_REVIEW = ["pending", "approved", "changes_requested", "rejected"]


async def create_custom_order(request: Request):
    """
    Create a custom model order.
    Body: {
        model_size_id, finish_option_id, reference_image_url, generation_id,
        image_source, paint_extras, shipping_address, agreement_accepted,
        pricing (from pricing engine)
    }
    """
    try:
        user = get_current_user(request)
        if not user:
            return auth_error_response()

        body = await request.json()

        # Validate required fields
        required = ["model_size_id", "finish_option_id", "image_source", "agreement_accepted"]
        for field in required:
            if not body.get(field):
                return JSONResponse({"error": f"{field} is required"}, status_code=400)

        if not body.get("agreement_accepted"):
            return JSONResponse({"error": "You must accept the terms before placing an order"}, status_code=400)

        if not body.get("reference_image_url") and not body.get("generation_id"):
            return JSONResponse({"error": "An image upload or AI generation is required"}, status_code=400)

        # Fetch size details
        size_resp = supabase.table("model_sizes").select("*").eq("id", body["model_size_id"]).execute()
        if not size_resp.data:
            return JSONResponse({"error": "Size not found"}, status_code=404)
        size = size_resp.data[0]

        # Fetch finish details
        finish_resp = supabase.table("finish_options").select("*").eq("id", body["finish_option_id"]).execute()
        if not finish_resp.data:
            return JSONResponse({"error": "Finish option not found"}, status_code=404)
        finish = finish_resp.data[0]

        # Calculate prices
        size_price = float(size.get("sale_price") or size["price"]) if size.get("is_on_sale") and size.get("sale_price") else float(size["price"])
        finish_price = float(finish.get("sale_price") or finish["base_price"]) if finish.get("is_on_sale") and finish.get("sale_price") else float(finish["base_price"])

        # Painting tier (for 'painted' finish)
        painting_tier_id = None
        painting_tier_name = None
        painting_price = 0.0

        if finish["slug"] == "painted":
            mapping_resp = supabase.table("painting_tier_mappings").select("*, painting_tiers(*)").eq("model_size_id", body["model_size_id"]).execute()
            if mapping_resp.data:
                m = mapping_resp.data[0]
                tier = m.get("painting_tiers", {})
                painting_tier_id = tier.get("id")
                painting_tier_name = tier.get("name")
                painting_price = float(m["price_override"]) if m.get("price_override") is not None else float(tier.get("price", 0))

        # Process paint extras
        extras_total = 0.0
        paint_extras_data = []

        if finish["slug"] == "diy_kit" and body.get("paint_extras"):
            for extra in body["paint_extras"]:
                color_resp = supabase.table("paint_colors").select("*").eq("id", extra["paint_color_id"]).execute()
                if not color_resp.data:
                    continue
                color = color_resp.data[0]
                qty = int(extra.get("quantity", 1))
                unit_price = float(color.get("sale_price") or color["price"]) if color.get("is_on_sale") and color.get("sale_price") else float(color["price"])
                extras_total += unit_price * qty
                paint_extras_data.append({
                    "paint_color_id": color["id"],
                    "color_name": color["name"],
                    "hex_code": color.get("hex_code", "#000000"),
                    "quantity": qty,
                    "unit_price": unit_price,
                    "is_on_sale": bool(color.get("is_on_sale"))
                })

        # Subtotal before discount
        subtotal = size_price + finish_price + painting_price + extras_total

        # Membership discount
        from app.core.auth_utils import get_user_membership_discount
        discount_pct = get_user_membership_discount(user)
        membership_tier = user.get("subscription_plan", "starter")
        if membership_tier == "starter":
            membership_tier = None

        # Calculate discount-eligible amount (exclude sale items)
        disc_eligible = 0.0
        if not size.get("is_on_sale"):
            disc_eligible += size_price
        if not finish.get("is_on_sale"):
            disc_eligible += finish_price
        disc_eligible += painting_price
        for pe in paint_extras_data:
            if not pe["is_on_sale"]:
                disc_eligible += pe["unit_price"] * pe["quantity"]

        discount_amount = round(disc_eligible * (discount_pct / 100), 2)

        # Delivery
        ds = supabase.table("delivery_settings").select("*").limit(1).execute()
        threshold = 50.0
        std_delivery = 4.99
        if ds.data:
            threshold = float(ds.data[0].get("free_delivery_threshold", 50))
            std_delivery = float(ds.data[0].get("standard_delivery_price", 4.99))
        delivery_price = 0.0 if subtotal >= threshold else std_delivery

        total = round(subtotal - discount_amount + delivery_price, 2)

        # Create order
        order_id = str(uuid4())
        order = {
            "id": order_id,
            "user_id": user["id"],
            "reference_image_url": body.get("reference_image_url"),
            "generation_id": body.get("generation_id"),
            "image_source": body["image_source"],
            "model_size_id": body["model_size_id"],
            "size_label": size["size_label"],
            "size_price": size_price,
            "finish_option_id": body["finish_option_id"],
            "finish_name": finish["name"],
            "finish_price": finish_price,
            "painting_tier_id": painting_tier_id,
            "painting_tier_name": painting_tier_name,
            "painting_price": painting_price,
            "extras_total": round(extras_total, 2),
            "subtotal_before_discount": round(subtotal, 2),
            "membership_tier": membership_tier,
            "discount_percentage": discount_pct,
            "discount_amount": discount_amount,
            "delivery_price": delivery_price,
            "total": total,
            "shipping_address": body.get("shipping_address"),
            "status": "new_order",
            "review_status": "pending",
            "agreement_accepted": True,
            "agreement_accepted_at": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        order_resp = supabase.table("custom_orders").insert(order).execute()

        # Insert paint extras
        if paint_extras_data:
            for pe in paint_extras_data:
                pe["id"] = str(uuid4())
                pe["order_id"] = order_id
                pe["created_at"] = datetime.utcnow().isoformat()
            supabase.table("order_paint_extras").insert(paint_extras_data).execute()

        result = order_resp.data[0]
        result["paint_extras"] = paint_extras_data

        # Send confirmation emails (fire and forget)
        try:
            from app.utils.email import send_order_confirmation, send_admin_new_order
            import asyncio
            asyncio.create_task(send_order_confirmation(user["email"], order_id, total, size["size_label"], finish["name"]))
            asyncio.create_task(send_admin_new_order(order_id, user["email"], total, size["size_label"], finish["name"]))
        except Exception:
            pass

        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def initiate_checkout(request: Request):
    """
    Create order + Stripe checkout session.
    Returns {checkout_url, order_id} if Stripe is configured,
    or falls back to creating order directly (for dev/testing).
    """
    try:
        user = get_current_user(request)
        if not user:
            return auth_error_response()

        body = await request.json()

        required = ["model_size_id", "finish_option_id", "image_source", "agreement_accepted"]
        for field in required:
            if not body.get(field):
                return JSONResponse({"error": f"{field} is required"}, status_code=400)

        if not body.get("agreement_accepted"):
            return JSONResponse({"error": "You must accept the terms before placing an order"}, status_code=400)

        if not body.get("reference_image_url") and not body.get("generation_id"):
            return JSONResponse({"error": "An image upload or AI generation is required"}, status_code=400)

        # ── Pricing (same logic as create_custom_order) ──────────────────────
        size_resp = supabase.table("model_sizes").select("*").eq("id", body["model_size_id"]).execute()
        if not size_resp.data:
            return JSONResponse({"error": "Size not found"}, status_code=404)
        size = size_resp.data[0]

        finish_resp = supabase.table("finish_options").select("*").eq("id", body["finish_option_id"]).execute()
        if not finish_resp.data:
            return JSONResponse({"error": "Finish option not found"}, status_code=404)
        finish = finish_resp.data[0]

        size_price = float(size.get("sale_price") or size["price"]) if size.get("is_on_sale") and size.get("sale_price") else float(size["price"])
        finish_price = float(finish.get("sale_price") or finish["base_price"]) if finish.get("is_on_sale") and finish.get("sale_price") else float(finish["base_price"])

        painting_tier_id = None
        painting_tier_name = None
        painting_price = 0.0
        if finish["slug"] == "painted":
            mapping_resp = supabase.table("painting_tier_mappings").select("*, painting_tiers(*)").eq("model_size_id", body["model_size_id"]).execute()
            if mapping_resp.data:
                m = mapping_resp.data[0]
                tier = m.get("painting_tiers", {})
                painting_tier_id = tier.get("id")
                painting_tier_name = tier.get("name")
                painting_price = float(m["price_override"]) if m.get("price_override") is not None else float(tier.get("price", 0))

        extras_total = 0.0
        paint_extras_data = []
        if finish["slug"] == "diy_kit" and body.get("paint_extras"):
            for extra in body["paint_extras"]:
                color_resp = supabase.table("paint_colors").select("*").eq("id", extra["paint_color_id"]).execute()
                if not color_resp.data:
                    continue
                color = color_resp.data[0]
                qty = int(extra.get("quantity", 1))
                unit_price = float(color.get("sale_price") or color["price"]) if color.get("is_on_sale") and color.get("sale_price") else float(color["price"])
                extras_total += unit_price * qty
                paint_extras_data.append({
                    "paint_color_id": color["id"],
                    "color_name": color["name"],
                    "hex_code": color.get("hex_code", "#000000"),
                    "quantity": qty,
                    "unit_price": unit_price,
                    "is_on_sale": bool(color.get("is_on_sale"))
                })

        subtotal = size_price + finish_price + painting_price + extras_total
        from app.core.auth_utils import get_user_membership_discount
        discount_pct = get_user_membership_discount(user)
        membership_tier = user.get("subscription_plan", "starter")
        if membership_tier == "starter":
            membership_tier = None

        disc_eligible = 0.0
        if not size.get("is_on_sale"):
            disc_eligible += size_price
        if not finish.get("is_on_sale"):
            disc_eligible += finish_price
        disc_eligible += painting_price
        for pe in paint_extras_data:
            if not pe["is_on_sale"]:
                disc_eligible += pe["unit_price"] * pe["quantity"]
        discount_amount = round(disc_eligible * (discount_pct / 100), 2)

        ds = supabase.table("delivery_settings").select("*").limit(1).execute()
        threshold = 50.0
        std_delivery = 4.99
        if ds.data:
            threshold = float(ds.data[0].get("free_delivery_threshold", 50))
            std_delivery = float(ds.data[0].get("standard_delivery_price", 4.99))
        delivery_price = 0.0 if subtotal >= threshold else std_delivery
        total = round(subtotal - discount_amount + delivery_price, 2)

        # ── Build order record ────────────────────────────────────────────────
        order_id = str(uuid4())
        order = {
            "id": order_id,
            "user_id": user["id"],
            "reference_image_url": body.get("reference_image_url"),
            "generation_id": body.get("generation_id"),
            "image_source": body["image_source"],
            "model_size_id": body["model_size_id"],
            "size_label": size["size_label"],
            "size_price": size_price,
            "finish_option_id": body["finish_option_id"],
            "finish_name": finish["name"],
            "finish_price": finish_price,
            "painting_tier_id": painting_tier_id,
            "painting_tier_name": painting_tier_name,
            "painting_price": painting_price,
            "extras_total": round(extras_total, 2),
            "subtotal_before_discount": round(subtotal, 2),
            "membership_tier": membership_tier,
            "discount_percentage": discount_pct,
            "discount_amount": discount_amount,
            "delivery_price": delivery_price,
            "total": total,
            "shipping_address": body.get("shipping_address"),
            "status": "awaiting_payment",
            "review_status": "pending",
            "agreement_accepted": True,
            "agreement_accepted_at": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        supabase.table("custom_orders").insert(order).execute()

        if paint_extras_data:
            for pe in paint_extras_data:
                pe["id"] = str(uuid4())
                pe["order_id"] = order_id
                pe["created_at"] = datetime.utcnow().isoformat()
            supabase.table("order_paint_extras").insert(paint_extras_data).execute()

        # ── Stripe checkout session ───────────────────────────────────────────
        if settings.stripe_secret_key:
            try:
                session = stripe_lib.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{
                        "price_data": {
                            "currency": "gbp",
                            "product_data": {
                                "name": f"Custom 3D Print — {size['size_label']} {finish['name']}",
                            },
                            "unit_amount": int(total * 100),
                        },
                        "quantity": 1,
                    }],
                    mode="payment",
                    success_url=f"{settings.frontend_url}/orders/success?session_id={{CHECKOUT_SESSION_ID}}&order_id={order_id}",
                    cancel_url=f"{settings.frontend_url}/builder/checkout?cancelled=true",
                    customer_email=user.get("email"),
                    metadata={"order_id": order_id, "user_id": user["id"], "type": "custom_order"},
                )
                return {"checkout_url": session.url, "order_id": order_id}
            except Exception as stripe_err:
                # Clean up the awaiting_payment order on Stripe error
                supabase.table("custom_orders").delete().eq("id", order_id).execute()
                return JSONResponse({"error": f"Payment setup failed: {str(stripe_err)}"}, status_code=500)

        # Stripe not configured — activate order immediately (dev/test mode)
        supabase.table("custom_orders").update({"status": "new_order"}).eq("id", order_id).execute()
        try:
            from app.utils.email import send_order_confirmation, send_admin_new_order
            import asyncio
            asyncio.create_task(send_order_confirmation(user["email"], order_id, total, size["size_label"], finish["name"]))
            asyncio.create_task(send_admin_new_order(order_id, user["email"], total, size["size_label"], finish["name"]))
        except Exception:
            pass
        return {"checkout_url": None, "order_id": order_id}

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def list_custom_orders(request: Request):
    """List current user's custom orders."""
    try:
        user = get_current_user(request)
        if not user:
            return auth_error_response()

        resp = supabase.table("custom_orders").select("*").eq("user_id", user["id"]).order("created_at", desc=True).execute()
        return resp.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_custom_order(request: Request, order_id: str):
    """Get a custom order with extras and notes."""
    try:
        user = get_current_user(request)
        if not user:
            return auth_error_response()

        is_admin = user.get("role") == "admin"
        query = supabase.table("custom_orders").select("*").eq("id", order_id)
        if not is_admin:
            query = query.eq("user_id", user["id"])

        resp = query.execute()
        if not resp.data:
            return JSONResponse({"error": "Order not found"}, status_code=404)

        order = resp.data[0]

        # Get extras
        extras = supabase.table("order_paint_extras").select("*").eq("order_id", order_id).execute()
        order["paint_extras"] = extras.data or []

        # Get notes (admin only sees all, user sees customer-facing)
        notes_query = supabase.table("order_notes").select("*").eq("order_id", order_id).order("created_at", desc=True)
        if not is_admin:
            notes_query = notes_query.eq("note_type", "customer")
        notes = notes_query.execute()
        order["notes"] = notes.data or []

        return order
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def admin_list_custom_orders(request: Request, limit: int = 50, offset: int = 0, status: str = None):
    """Admin: list all custom orders."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        query = supabase.table("custom_orders").select("*, users(name, email)").order("created_at", desc=True).range(offset, offset + limit - 1)
        if status:
            query = query.eq("status", status)

        resp = query.execute()
        return resp.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_order_status(request: Request, order_id: str):
    """Admin: update order status."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        new_status = body.get("status")
        if new_status not in VALID_STATUSES:
            return JSONResponse({"error": f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}"}, status_code=400)

        # Check review status — cannot progress past in_review if not approved
        order_resp = supabase.table("custom_orders").select("review_status").eq("id", order_id).execute()
        if not order_resp.data:
            return JSONResponse({"error": "Order not found"}, status_code=404)

        review = order_resp.data[0].get("review_status")
        production_statuses = ["printing", "kit_packing", "painting", "completed", "shipped"]
        if new_status in production_statuses and review != "approved":
            return JSONResponse({"error": "Order must be approved before production can begin"}, status_code=400)

        update = {"status": new_status, "updated_at": datetime.utcnow().isoformat()}
        resp = supabase.table("custom_orders").update(update).eq("id", order_id).execute()
        if not resp.data:
            return JSONResponse({"error": "Order not found"}, status_code=404)

        # Email customer about status change
        try:
            order_data = resp.data[0]
            user_resp = supabase.table("users").select("email").eq("id", order_data.get("user_id")).execute()
            if user_resp.data:
                from app.utils.email import send_status_update
                import asyncio
                asyncio.create_task(send_status_update(user_resp.data[0]["email"], order_id, new_status))
        except Exception:
            pass

        return resp.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def review_order(request: Request, order_id: str):
    """
    Admin: approve, request changes, or reject an order.
    Body: { "review_status": "approved" | "changes_requested" | "rejected", "note": "optional" }
    """
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        new_review = body.get("review_status")
        if new_review not in VALID_REVIEW:
            return JSONResponse({"error": f"Invalid review status. Must be one of: {', '.join(VALID_REVIEW)}"}, status_code=400)

        update = {
            "review_status": new_review,
            "updated_at": datetime.utcnow().isoformat()
        }

        if new_review == "approved":
            update["status"] = "in_review"

        resp = supabase.table("custom_orders").update(update).eq("id", order_id).execute()
        if not resp.data:
            return JSONResponse({"error": "Order not found"}, status_code=404)

        # Add note if provided
        note_text = body.get("note")
        if note_text:
            note = {
                "id": str(uuid4()),
                "order_id": order_id,
                "admin_id": admin["id"],
                "admin_name": admin["name"],
                "note": note_text,
                "note_type": body.get("note_type", "internal"),
                "created_at": datetime.utcnow().isoformat()
            }
            supabase.table("order_notes").insert(note).execute()

        return {"message": f"Order review status updated to {new_review}", "order": resp.data[0]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def add_order_note(request: Request, order_id: str):
    """Admin: add a note to an order."""
    try:
        admin = require_admin(request)
        if not admin:
            return admin_error_response()

        body = await request.json()
        note_text = body.get("note")
        if not note_text:
            return JSONResponse({"error": "note is required"}, status_code=400)

        note = {
            "id": str(uuid4()),
            "order_id": order_id,
            "admin_id": admin["id"],
            "admin_name": admin["name"],
            "note": note_text,
            "note_type": body.get("note_type", "internal"),
            "created_at": datetime.utcnow().isoformat()
        }

        resp = supabase.table("order_notes").insert(note).execute()
        return resp.data[0]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
