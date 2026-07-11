"""
Pricing Controller — Dynamic pricing engine.
Calculates the total price based on size + finish + extras + membership discount + delivery.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.auth_utils import get_current_user, get_user_membership_discount

supabase = get_supabase_client()


async def calculate_price(request: Request):
    """
    Calculate the full price breakdown for a custom model order.

    Expected body:
    {
        "model_size_id": "uuid",
        "finish_option_id": "uuid",
        "paint_extras": [
            { "paint_color_id": "uuid", "quantity": 2 },
            ...
        ]
    }

    Returns a full pricing breakdown including membership discount and delivery.
    """
    try:
        body = await request.json()
        size_id = body.get("model_size_id")
        finish_id = body.get("finish_option_id")
        paint_extras = body.get("paint_extras", [])

        if not size_id or not finish_id:
            return JSONResponse({"error": "model_size_id and finish_option_id are required"}, status_code=400)

        # 1. Get size price
        size_response = supabase.table("model_sizes").select("*").eq("id", size_id).execute()
        if not size_response.data:
            return JSONResponse({"error": "Size not found"}, status_code=404)
        size = size_response.data[0]
        size_price = float(size.get("sale_price") or size["price"]) if size.get("is_on_sale") and size.get("sale_price") else float(size["price"])
        size_is_sale = bool(size.get("is_on_sale"))

        # 2. Get finish option
        finish_response = supabase.table("finish_options").select("*").eq("id", finish_id).execute()
        if not finish_response.data:
            return JSONResponse({"error": "Finish option not found"}, status_code=404)
        finish = finish_response.data[0]
        finish_slug = finish["slug"]
        finish_base_price = float(finish.get("sale_price") or finish["base_price"]) if finish.get("is_on_sale") and finish.get("sale_price") else float(finish["base_price"])
        finish_is_sale = bool(finish.get("is_on_sale"))

        # 3. Get painting tier price (only for 'painted' finish)
        painting_price = 0.0
        painting_tier_id = None
        painting_tier_name = None
        painting_is_sale = False

        if finish_slug == "painted":
            mapping_response = supabase.table("painting_tier_mappings").select(
                "*, painting_tiers(*)"
            ).eq("model_size_id", size_id).execute()

            if mapping_response.data:
                mapping = mapping_response.data[0]
                tier = mapping.get("painting_tiers", {})
                painting_tier_id = tier.get("id")
                painting_tier_name = tier.get("name")

                # Use override if set, otherwise tier base price
                if mapping.get("price_override") is not None:
                    painting_price = float(mapping["price_override"])
                else:
                    painting_price = float(tier.get("price", 0))

        # 4. Calculate extras total
        extras_total = 0.0
        extras_breakdown = []
        discount_eligible_extras = 0.0
        non_discount_extras = 0.0

        for extra in paint_extras:
            color_id = extra.get("paint_color_id")
            qty = int(extra.get("quantity", 1))

            if not color_id or qty < 1:
                continue

            color_response = supabase.table("paint_colors").select("*").eq("id", color_id).execute()
            if not color_response.data:
                continue

            color = color_response.data[0]
            unit_price = float(color.get("sale_price") or color["price"]) if color.get("is_on_sale") and color.get("sale_price") else float(color["price"])
            is_sale = bool(color.get("is_on_sale"))
            line_total = unit_price * qty

            extras_breakdown.append({
                "paint_color_id": color_id,
                "color_name": color["name"],
                "hex_code": color.get("hex_code", "#000000"),
                "quantity": qty,
                "unit_price": unit_price,
                "line_total": line_total,
                "is_on_sale": is_sale
            })

            extras_total += line_total
            if is_sale:
                non_discount_extras += line_total
            else:
                discount_eligible_extras += line_total

        # 5. Calculate subtotal before discount
        subtotal = size_price + finish_base_price + painting_price + extras_total

        # 6. Calculate discount-eligible amount (full-price items only)
        discount_eligible = 0.0
        if not size_is_sale:
            discount_eligible += size_price
        if not finish_is_sale:
            discount_eligible += finish_base_price
        if not painting_is_sale:
            discount_eligible += painting_price
        discount_eligible += discount_eligible_extras

        # 7. Get membership discount
        discount_percentage = 0.0
        membership_tier = None
        current_user = get_current_user(request)
        if current_user:
            discount_percentage = get_user_membership_discount(current_user)
            plan = current_user.get("subscription_plan", "starter")
            if plan and plan != "starter":
                membership_tier = plan

        discount_amount = round(discount_eligible * (discount_percentage / 100), 2)

        # 8. Calculate delivery
        delivery_settings = supabase.table("delivery_settings").select("*").limit(1).execute()
        free_threshold = 50.0
        standard_delivery = 4.99

        if delivery_settings.data:
            ds = delivery_settings.data[0]
            free_threshold = float(ds.get("free_delivery_threshold", 50))
            standard_delivery = float(ds.get("standard_delivery_price", 4.99))

        # Free delivery is based on subtotal BEFORE discount
        qualifies_free_delivery = subtotal >= free_threshold
        delivery_price = 0.0 if qualifies_free_delivery else standard_delivery
        amount_to_free_delivery = max(0, free_threshold - subtotal) if not qualifies_free_delivery else 0

        # 9. Final total
        total = subtotal - discount_amount + delivery_price

        return {
            "size": {
                "id": size["id"],
                "size_label": size["size_label"],
                "price": size_price,
                "is_on_sale": size_is_sale
            },
            "finish": {
                "id": finish["id"],
                "name": finish["name"],
                "slug": finish_slug,
                "price": finish_base_price,
                "is_on_sale": finish_is_sale
            },
            "painting": {
                "tier_id": painting_tier_id,
                "tier_name": painting_tier_name,
                "price": painting_price
            } if finish_slug == "painted" else None,
            "extras": extras_breakdown,
            "extras_total": round(extras_total, 2),

            "subtotal_before_discount": round(subtotal, 2),
            "discount_eligible_amount": round(discount_eligible, 2),
            "membership_tier": membership_tier,
            "discount_percentage": discount_percentage,
            "discount_amount": round(discount_amount, 2),

            "delivery": {
                "qualifies_free": qualifies_free_delivery,
                "price": round(delivery_price, 2),
                "free_threshold": free_threshold,
                "amount_to_free": round(amount_to_free_delivery, 2)
            },

            "total": round(total, 2)
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
