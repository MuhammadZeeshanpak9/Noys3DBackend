import httpx
import logging
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def send_email(to: str, subject: str, html: str):
    if not settings.resend_api_key:
        return
    from_addr = f"Noys 3D Prints <{settings.admin_email}>" if settings.admin_email else "Noys 3D Prints <onboarding@resend.dev>"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}", "Content-Type": "application/json"},
                json={"from": from_addr, "to": [to], "subject": subject, "html": html},
            )
            resp.raise_for_status()
    except Exception as e:
        logger.error(f"Email send failed to {to}: {e}")


async def send_order_confirmation(customer_email: str, order_id: str, total: float, size_mm: int, finish_name: str):
    subject = "Your Noys 3D Prints order has been received"
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px">
      <h1 style="color:#0c2a50">Order Received!</h1>
      <p>Thank you for your order. We'll review your image and get in touch before production begins.</p>
      <div style="background:#f0f4ff;border-radius:8px;padding:16px;margin:16px 0">
        <p style="margin:4px 0"><strong>Order ID:</strong> {order_id[:8].upper()}</p>
        <p style="margin:4px 0"><strong>Configuration:</strong> {size_mm}mm — {finish_name}</p>
        <p style="margin:4px 0"><strong>Total paid:</strong> £{total:.2f}</p>
      </div>
      <p>You can track your order status at any time in <a href="{settings.frontend_url}/profile/history" style="color:#2563eb">My Orders</a>.</p>
      <p style="color:#888;font-size:13px">Noys 3D Prints · noys3dprints.co.uk</p>
    </div>
    """
    await send_email(customer_email, subject, html)


async def send_admin_new_order(order_id: str, customer_email: str, total: float, size_mm: int, finish_name: str):
    if not settings.admin_email:
        return
    subject = f"New custom order — £{total:.2f}"
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px">
      <h1 style="color:#0c2a50">New Custom Order</h1>
      <div style="background:#f0f4ff;border-radius:8px;padding:16px;margin:16px 0">
        <p style="margin:4px 0"><strong>Order ID:</strong> {order_id[:8].upper()}</p>
        <p style="margin:4px 0"><strong>Customer:</strong> {customer_email}</p>
        <p style="margin:4px 0"><strong>Configuration:</strong> {size_mm}mm — {finish_name}</p>
        <p style="margin:4px 0"><strong>Total:</strong> £{total:.2f}</p>
      </div>
      <a href="{settings.frontend_url}/admin/custom-orders/{order_id}" style="background:#1a4073;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">
        Review Order
      </a>
    </div>
    """
    await send_email(settings.admin_email, subject, html)


async def send_status_update(customer_email: str, order_id: str, new_status: str):
    STATUS_MESSAGES = {
        "in_review": ("Your order is being reviewed", "Our team is reviewing your image and configuration."),
        "printing": ("Your model is being printed!", "Great news — your 3D model is now being printed."),
        "kit_packing": ("Your kit is being packed", "Your paint kit is being assembled and packed."),
        "painting": ("Your model is being painted", "Our artists are now painting your model."),
        "completed": ("Your order is complete", "Your order has been completed and is ready to dispatch."),
        "shipped": ("Your order has been shipped!", "Your model is on its way to you."),
        "cancelled": ("Your order has been cancelled", "Your custom order has been cancelled. Please contact us if you have questions."),
    }
    if new_status not in STATUS_MESSAGES:
        return
    subject_suffix, body_text = STATUS_MESSAGES[new_status]
    subject = f"Order update — {subject_suffix}"
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px">
      <h1 style="color:#0c2a50">Order Update</h1>
      <p>{body_text}</p>
      <div style="background:#f0f4ff;border-radius:8px;padding:16px;margin:16px 0">
        <p style="margin:4px 0"><strong>Order ID:</strong> {order_id[:8].upper()}</p>
        <p style="margin:4px 0"><strong>Status:</strong> {subject_suffix}</p>
      </div>
      <a href="{settings.frontend_url}/orders/{order_id}" style="background:#1a4073;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block">
        View Order
      </a>
      <p style="color:#888;font-size:13px;margin-top:24px">Noys 3D Prints · noys3dprints.co.uk</p>
    </div>
    """
    await send_email(customer_email, subject, html)
