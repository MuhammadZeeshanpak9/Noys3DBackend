"""
Shared authentication utilities.
Eliminates the duplicated _get_current_user helper from every controller.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from app.db.connection import get_supabase_client
from app.core.security import decode_access_token
from typing import Optional


supabase = get_supabase_client()


def get_current_user(request: Request) -> Optional[dict]:
    """Extract and validate the current user from the Authorization header."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    response = supabase.table("users").select("*").eq("id", user_id).execute()

    if not response.data:
        return None

    return response.data[0]


def require_admin(request: Request) -> Optional[dict]:
    """Require the current user to be an admin. Returns user dict or None."""
    user = get_current_user(request)
    if not user:
        return None
    if user.get("role") != "admin":
        return None
    return user


def auth_error_response():
    """Standard 401 response for missing/invalid auth."""
    return JSONResponse({"error": "Authentication required"}, status_code=401)


def admin_error_response():
    """Standard 403 response for non-admin users."""
    return JSONResponse({"error": "Admin access required"}, status_code=403)


def get_user_membership_discount(user: dict) -> float:
    """
    Get the membership discount percentage for a user.
    Returns 0 if no active membership or starter plan.
    """
    plan_name = user.get("subscription_plan", "starter")
    if not plan_name or plan_name == "starter":
        return 0.0

    try:
        plan_response = supabase.table("plans").select("discount_percentage").eq(
            "name", plan_name.capitalize()
        ).execute()

        if plan_response.data and plan_response.data[0].get("discount_percentage"):
            return float(plan_response.data[0]["discount_percentage"])
    except Exception:
        pass

    # Fallback defaults
    defaults = {"bronze": 10.0, "silver": 15.0, "gold": 25.0}
    return defaults.get(plan_name.lower(), 0.0)
