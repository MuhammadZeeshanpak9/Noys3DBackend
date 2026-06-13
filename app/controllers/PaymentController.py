from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.security import decode_access_token
from app.core.config import get_settings
from datetime import datetime
from uuid import uuid4
from typing import Optional
import json
import stripe as stripe_lib

supabase = get_supabase_client()
settings = get_settings()

if settings.stripe_secret_key:
    # .strip() guards against trailing newlines / whitespace that sneak in
    # when pasting the key into a hosting dashboard's env var input.
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


async def subscribe_to_plan(request: Request):
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        body = await request.json()
        return await _subscribe_to_plan_with_body(request, current_user, body)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _subscribe_to_plan_with_body(request: Request, current_user: dict, body: dict):

    try:
        plan_id = body.get("plan_id") or body.get("item_id")
        success_url = body.get("success_url", f"{settings.frontend_url}/payment?status=success")
        cancel_url = body.get("cancel_url", f"{settings.frontend_url}/payment?status=cancelled")

        if not plan_id:
            return JSONResponse({"error": "Plan ID is required"}, status_code=400)

        plan_response = supabase.table("plans").select("*").eq("id", plan_id).execute()
        if not plan_response.data:
            return JSONResponse({"error": "Plan not found"}, status_code=404)

        plan = plan_response.data[0]

        # Hard requirement: Stripe must be configured. We never grant a paid
        # subscription without a real Stripe Checkout flow.
        if not settings.stripe_secret_key:
            return JSONResponse(
                {"error": "Payments are not configured on this server. Please contact support."},
                status_code=503,
            )

        try:
            # Build a Stripe line item from our plan record. Using price_data
            # avoids the need for an admin-maintained Stripe Price ID on every
            # plan — Stripe creates the underlying product/price on demand.
            if plan.get("stripe_price_id"):
                line_items = [{"price": plan["stripe_price_id"], "quantity": 1}]
            else:
                line_items = [{
                    "price_data": {
                        "currency": "gbp",
                        "product_data": {"name": plan["name"]},
                        "unit_amount": int(round(float(plan["price"]) * 100)),
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }]

            checkout_session = stripe_lib.checkout.Session.create(
                payment_method_types=["card"],
                line_items=line_items,
                mode="subscription",
                success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=cancel_url,
                customer_email=current_user.get("email"),
                metadata={
                    "user_id": current_user["id"],
                    "plan_id": plan_id,
                    "type": "subscription"
                }
            )
            
            pending_payment = {
                "id": str(uuid4()),
                "user_id": current_user["id"],
                "type": "subscription",
                "amount": plan["price"],
                "status": "pending",
                "stripe_payment_intent_id": checkout_session.id,
                "metadata": json.dumps({"plan_id": plan_id, "plan_name": plan["name"]}),
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            supabase.table("payments").insert(pending_payment).execute()
            
            return {"checkout_url": checkout_session.url, "session_id": checkout_session.id}
        except Exception as stripe_error:
            return JSONResponse({"error": f"Stripe error: {str(stripe_error)}"}, status_code=500)
        
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def buy_credits(request: Request):
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        body = await request.json()
        return await _buy_credits_with_body(request, current_user, body)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _buy_credits_with_body(request: Request, current_user: dict, body: dict):

    try:
        credit_pack_id = body.get("credit_pack_id") or body.get("item_id")
        success_url = body.get("success_url", f"{settings.frontend_url}/payment?status=success")
        cancel_url = body.get("cancel_url", f"{settings.frontend_url}/payment?status=cancelled")

        if not credit_pack_id:
            return JSONResponse({"error": "Credit pack ID is required"}, status_code=400)

        pack_response = supabase.table("credit_packs").select("*").eq("id", credit_pack_id).execute()
        if not pack_response.data:
            return JSONResponse({"error": "Credit pack not found"}, status_code=404)

        pack = pack_response.data[0]

        # Hard requirement: Stripe must be configured. We never grant credits
        # without a real Stripe Checkout flow — otherwise anyone could click
        # "Buy" and get free credits.
        if not settings.stripe_secret_key:
            return JSONResponse(
                {"error": "Payments are not configured on this server. Please contact support."},
                status_code=503,
            )

        try:
            if pack.get("stripe_price_id"):
                line_items = [{"price": pack["stripe_price_id"], "quantity": 1}]
            else:
                line_items = [{
                    "price_data": {
                        "currency": "gbp",
                        "product_data": {"name": f"{pack['credits']} AI Credits"},
                        "unit_amount": int(round(float(pack["price"]) * 100)),
                    },
                    "quantity": 1,
                }]

            checkout_session = stripe_lib.checkout.Session.create(
                payment_method_types=["card"],
                line_items=line_items,
                mode="payment",
                success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=cancel_url,
                customer_email=current_user.get("email"),
                metadata={
                    "user_id": current_user["id"],
                    "pack_id": credit_pack_id,
                    "credits": pack["credits"],
                    "type": "credit_pack"
                }
            )
            
            pending_payment = {
                "id": str(uuid4()),
                "user_id": current_user["id"],
                "type": "credit_pack",
                "amount": pack["price"],
                "status": "pending",
                "stripe_payment_intent_id": checkout_session.id,
                "metadata": json.dumps({"pack_id": credit_pack_id, "credits": pack["credits"]}),
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            supabase.table("payments").insert(pending_payment).execute()
            
            return {"checkout_url": checkout_session.url, "session_id": checkout_session.id}
        except Exception as stripe_error:
            return JSONResponse({"error": f"Stripe error: {str(stripe_error)}"}, status_code=500)
        
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def create_checkout_session(request: Request):

    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        body = await request.json()
        # Normalize the type name — the frontend pricing page sends
        # "subscription"/"credits" but our helpers were written to expect
        # "plan"/"credit_pack". Accept both.
        raw_type = (body.get("type") or "").lower()
        item_id = body.get("item_id") or body.get("plan_id") or body.get("credit_pack_id")

        if raw_type in ("plan", "subscription", "subscriptions"):
            # Inject plan_id so subscribe_to_plan finds it regardless of field name used.
            body["plan_id"] = item_id
            return await _subscribe_to_plan_with_body(request, current_user, body)
        elif raw_type in ("credit_pack", "credits", "credit", "credit_packs"):
            body["credit_pack_id"] = item_id
            return await _buy_credits_with_body(request, current_user, body)
        else:
            return JSONResponse(
                {"error": f"Unknown payment type '{raw_type}'. Expected 'subscription' or 'credits'."},
                status_code=400,
            )

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def list_payments(request: Request):
    
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        if current_user.get("role") == "admin":
            response = supabase.table("payments").select("*").order("created_at", desc=True).execute()
        else:
            response = supabase.table("payments").select("*").eq("user_id", current_user["id"]).order("created_at", desc=True).execute()
        
        return response.data
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _fulfil_completed_session(session: dict) -> dict:
    """Apply the post-payment business logic for a paid Stripe Checkout
    Session. Idempotent — uses the payments table's status as a lock so
    re-running on the same session_id never double-grants credits.

    Returns a small dict describing what was applied, for the verify
    endpoint to relay back to the frontend.
    """
    session_id = session.get("id")
    metadata = session.get("metadata") or {}
    user_id = metadata.get("user_id")
    payment_type = metadata.get("type")

    # Idempotency: if the payment row is already marked completed, do nothing.
    existing = (
        supabase.table("payments")
        .select("status")
        .eq("stripe_payment_intent_id", session_id)
        .execute()
    )
    already_done = bool(existing.data) and existing.data[0].get("status") == "completed"
    if already_done:
        return {"already_processed": True, "type": payment_type}

    if not user_id:
        return {"applied": False, "reason": "no user_id in metadata"}

    if payment_type == "subscription":
        plan_id = metadata.get("plan_id")
        plan_resp = supabase.table("plans").select("*").eq("id", plan_id).execute()
        if plan_resp.data:
            plan = plan_resp.data[0]
            user_resp = supabase.table("users").select("credits").eq("id", user_id).execute()
            current_credits = user_resp.data[0].get("credits", 0) if user_resp.data else 0
            supabase.table("users").update({
                "subscription_plan": plan["name"].lower().replace(" ", "_"),
                "credits": current_credits + plan.get("credits", 0),
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", user_id).execute()

    elif payment_type == "credit_pack":
        credits = metadata.get("credits", 0)
        if credits:
            user_resp = supabase.table("users").select("credits").eq("id", user_id).execute()
            if user_resp.data:
                current_credits = user_resp.data[0].get("credits", 0)
                supabase.table("users").update({
                    "credits": current_credits + int(credits),
                    "updated_at": datetime.utcnow().isoformat(),
                }).eq("id", user_id).execute()

    elif payment_type == "shop_order":
        order_id = metadata.get("order_id")
        if order_id:
            # Guard on awaiting_payment so a re-delivered webhook is a no-op
            # (no duplicate emails / status flips).
            order_resp = supabase.table("orders").update({
                "status": "processing",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", order_id).eq("status", "awaiting_payment").execute()

            if order_resp.data:
                order_data = order_resp.data[0]
                user_resp = supabase.table("users").select("email").eq("id", user_id).execute()
                if user_resp.data:
                    try:
                        from app.utils.email import send_shop_order_confirmation, send_admin_shop_order
                        import asyncio
                        cust_email = user_resp.data[0]["email"]
                        items = order_data.get("items") or []
                        summary = ", ".join(
                            f"{int(i.get('quantity', 1))}x {i.get('name', 'item')}" for i in items
                        )
                        total = float(order_data.get("total", 0))
                        asyncio.create_task(send_shop_order_confirmation(cust_email, order_id, total, summary))
                        asyncio.create_task(send_admin_shop_order(order_id, cust_email, total, summary))
                    except Exception:
                        pass

    elif payment_type == "custom_order":
        order_id = metadata.get("order_id")
        if order_id:
            order_resp = supabase.table("custom_orders").update({
                "status": "new_order",
                "updated_at": datetime.utcnow().isoformat(),
            }).eq("id", order_id).eq("status", "awaiting_payment").execute()

            if order_resp.data:
                order_data = order_resp.data[0]
                user_resp = supabase.table("users").select("email").eq("id", user_id).execute()
                if user_resp.data:
                    try:
                        from app.utils.email import send_order_confirmation, send_admin_new_order
                        import asyncio
                        cust_email = user_resp.data[0]["email"]
                        asyncio.create_task(send_order_confirmation(
                            cust_email, order_id,
                            float(order_data.get("total", 0)),
                            int(order_data.get("size_mm", 0)),
                            order_data.get("finish_name", ""),
                        ))
                        asyncio.create_task(send_admin_new_order(
                            order_id, cust_email,
                            float(order_data.get("total", 0)),
                            int(order_data.get("size_mm", 0)),
                            order_data.get("finish_name", ""),
                        ))
                    except Exception:
                        pass

    # Mark the payment row as completed last — protects the idempotency check.
    supabase.table("payments").update({
        "status": "completed",
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("stripe_payment_intent_id", session_id).execute()

    return {"applied": True, "type": payment_type}


async def stripe_webhook(request: Request):
    try:
        if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
            return JSONResponse({"error": "Stripe not configured"}, status_code=503)

        payload = await request.body()
        sig_header = request.headers.get("stripe-signature")

        try:
            event = stripe_lib.Webhook.construct_event(
                payload, sig_header, settings.stripe_webhook_secret.strip()
            )
        except ValueError:
            return JSONResponse({"error": "Invalid payload"}, status_code=400)
        except stripe_lib.error.SignatureVerificationError:
            return JSONResponse({"error": "Invalid signature"}, status_code=400)

        if event["type"] == "checkout.session.completed":
            _fulfil_completed_session(event["data"]["object"])

        return {"status": "success"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def verify_session(request: Request):
    """Webhook-independent fallback. The frontend calls this when the user
    lands on /payment?status=success&session_id=... — we ask Stripe directly
    whether the session was paid and, if so, apply the same fulfillment logic
    the webhook would. Idempotent, safe to call multiple times."""
    try:
        current_user = _get_current_user(request)
        if not current_user:
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        if not settings.stripe_secret_key:
            return JSONResponse({"error": "Stripe not configured"}, status_code=503)

        body = await request.json()
        session_id = body.get("session_id")
        if not session_id:
            return JSONResponse({"error": "session_id is required"}, status_code=400)

        try:
            session = stripe_lib.checkout.Session.retrieve(session_id)
        except Exception as stripe_err:
            return JSONResponse({"error": f"Stripe lookup failed: {stripe_err}"}, status_code=502)

        # Refuse to fulfil if the session isn't actually paid. For subscription
        # mode Stripe sets payment_status to "paid" on first invoice success.
        paid = session.get("payment_status") == "paid" or session.get("status") == "complete"
        if not paid:
            return JSONResponse(
                {"error": "Payment not completed", "payment_status": session.get("payment_status")},
                status_code=400,
            )

        # Defend against someone else's session being submitted: the metadata
        # user_id must match the caller's user id.
        meta_user_id = (session.get("metadata") or {}).get("user_id")
        if not meta_user_id or meta_user_id != current_user["id"]:
            return JSONResponse({"error": "Session does not belong to this user"}, status_code=403)

        result = _fulfil_completed_session(session)
        return {"status": "ok", **result}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_stripe_config(request: Request):
    
    try:
        if not settings.stripe_secret_key:
            return {"configured": False}
        
        return {
            "configured": True,
            "publishable_key": settings.stripe_publishable_key or None,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
