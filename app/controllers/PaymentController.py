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
    stripe_lib.api_key = settings.stripe_secret_key


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
        success_url = body.get("success_url", "https://noys-3d-print.vercel.app/payment?status=success")
        cancel_url = body.get("cancel_url", "https://noys-3d-print.vercel.app/payment?status=cancelled")

        if not plan_id:
            return JSONResponse({"error": "Plan ID is required"}, status_code=400)

        plan_response = supabase.table("plans").select("*").eq("id", plan_id).execute()
        if not plan_response.data:
            return JSONResponse({"error": "Plan not found"}, status_code=404)
        
        plan = plan_response.data[0]

        if not settings.stripe_secret_key or not plan.get("stripe_price_id"):
            payment = {
                "id": str(uuid4()),
                "user_id": current_user["id"],
                "type": "subscription",
                "amount": plan["price"],
                "status": "completed",
                "metadata": json.dumps({"plan_id": plan_id, "plan_name": plan["name"]}),
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }

            supabase.table("users").update({
                "subscription_plan": plan["name"].lower().replace(" ", "_"),
                "credits": current_user.get("credits", 0) + plan.get("credits", 0),
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", current_user["id"]).execute()
            
            supabase.table("payments").insert(payment).execute()
            return {"status": "completed", "message": "Subscription activated"}
        
        try:
            checkout_session = stripe_lib.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price": plan["stripe_price_id"],
                    "quantity": 1,
                }],
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
        success_url = body.get("success_url", "https://noys-3d-print.vercel.app/payment?status=success")
        cancel_url = body.get("cancel_url", "https://noys-3d-print.vercel.app/payment?status=cancelled")

        if not credit_pack_id:
            return JSONResponse({"error": "Credit pack ID is required"}, status_code=400)

        pack_response = supabase.table("credit_packs").select("*").eq("id", credit_pack_id).execute()
        if not pack_response.data:
            return JSONResponse({"error": "Credit pack not found"}, status_code=404)
        
        pack = pack_response.data[0]

        if not settings.stripe_secret_key or not pack.get("stripe_price_id"):
            payment = {
                "id": str(uuid4()),
                "user_id": current_user["id"],
                "type": "credit_pack",
                "amount": pack["price"],
                "status": "completed",
                "metadata": json.dumps({"pack_id": credit_pack_id, "credits": pack["credits"]}),
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }

            supabase.table("users").update({
                "credits": current_user.get("credits", 0) + pack["credits"],
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", current_user["id"]).execute()
            
            supabase.table("payments").insert(payment).execute()
            return {"status": "completed", "message": "Credits purchased"}
        
        try:
            checkout_session = stripe_lib.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price": pack["stripe_price_id"],
                    "quantity": 1,
                }],
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


async def stripe_webhook(request: Request):
    
    try:
        if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
            return JSONResponse({"error": "Stripe not configured"}, status_code=503)

        payload = await request.body()
        sig_header = request.headers.get("stripe-signature")
        
        try:
            event = stripe_lib.Webhook.construct_event(
                payload, sig_header, settings.stripe_webhook_secret
            )
        except ValueError:
            return JSONResponse({"error": "Invalid payload"}, status_code=400)
        except stripe_lib.error.SignatureVerificationError:
            return JSONResponse({"error": "Invalid signature"}, status_code=400)
        
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            user_id = session.get("metadata", {}).get("user_id")
            payment_type = session.get("metadata", {}).get("type")
            
            if user_id:
                if payment_type == "subscription":
                    plan_id = session.get("metadata", {}).get("plan_id")
                    plan_response = supabase.table("plans").select("*").eq("id", plan_id).execute()
                    if plan_response.data:
                        plan = plan_response.data[0]
                        supabase.table("users").update({
                            "subscription_plan": plan["name"].lower().replace(" ", "_"),
                            "credits": supabase.table("users").select("credits").eq("id", user_id).execute().data[0].get("credits", 0) + plan.get("credits", 0),
                            "updated_at": datetime.utcnow().isoformat()
                        }).eq("id", user_id).execute()
                
                elif payment_type == "credit_pack":
                    pack_id = session.get("metadata", {}).get("pack_id")
                    credits = session.get("metadata", {}).get("credits", 0)
                    if pack_id and credits:
                        user_response = supabase.table("users").select("credits").eq("id", user_id).execute()
                        if user_response.data:
                            current_credits = user_response.data[0].get("credits", 0)
                            supabase.table("users").update({
                                "credits": current_credits + int(credits),
                                "updated_at": datetime.utcnow().isoformat()
                            }).eq("id", user_id).execute()

                elif payment_type == "custom_order":
                    order_id = session.get("metadata", {}).get("order_id")
                    if order_id:
                        order_resp = supabase.table("custom_orders").update({
                            "status": "new_order",
                            "updated_at": datetime.utcnow().isoformat(),
                        }).eq("id", order_id).eq("status", "awaiting_payment").execute()

                        # Send confirmation emails
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

                supabase.table("payments").update({
                    "status": "completed"
                }).eq("stripe_payment_intent_id", session["id"]).execute()
        
        return {"status": "success"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_stripe_config(request: Request):
    
    try:
        if not settings.stripe_secret_key:
            return {"configured": False}
        
        return {
            "configured": True,
            "publishable_key": settings.stripe_secret_key.replace("sk_", "pk_") if settings.stripe_secret_key else None
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
