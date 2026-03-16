"""Email service for transactional emails.

Uses Python's standard smtplib via asyncio.to_thread so it does not block the
event loop.  When SMTP credentials are not configured (development mode) the
email content is logged instead of sent — no external dependency is required
during development.
"""
import asyncio
import logging
import secrets
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings
from app.core.cache import get_redis

logger = logging.getLogger(__name__)

# Redis key prefix and TTL for email verification tokens
_VERIFY_PREFIX = "email_verify:"
_VERIFY_TTL = 86_400  # 24 hours in seconds

# Redis key prefix and TTL for password reset tokens
_RESET_PREFIX = "password_reset:"
_RESET_TTL = 3_600  # 1 hour in seconds


# ── Token helpers ─────────────────────────────────────────────────────────────

def generate_verification_token() -> str:
    """Return a cryptographically secure URL-safe token (48 chars)."""
    return secrets.token_urlsafe(36)


async def store_verification_token(token: str, user_id: str) -> None:
    """Store token → user_id mapping in Redis with 24-hour TTL."""
    r = await get_redis()
    await r.setex(f"{_VERIFY_PREFIX}{token}", _VERIFY_TTL, user_id)


async def consume_verification_token(token: str) -> str | None:
    """Return user_id if the token is valid, then delete it.  Returns None if invalid."""
    r = await get_redis()
    key = f"{_VERIFY_PREFIX}{token}"
    user_id = await r.get(key)
    if user_id:
        await r.delete(key)
    return user_id


async def store_password_reset_token(token: str, user_id: str) -> None:
    """Store reset token → user_id mapping in Redis with 1-hour TTL."""
    r = await get_redis()
    await r.setex(f"{_RESET_PREFIX}{token}", _RESET_TTL, user_id)


async def consume_password_reset_token(token: str) -> str | None:
    """Return user_id if the reset token is valid, then delete it.  Returns None if invalid."""
    r = await get_redis()
    key = f"{_RESET_PREFIX}{token}"
    user_id = await r.get(key)
    if user_id:
        await r.delete(key)
    return user_id


# ── SMTP send ─────────────────────────────────────────────────────────────────

def _build_verification_email(to_email: str, full_name: str, verify_url: str) -> MIMEMultipart:
    """Build a MIME message for the email verification email."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Verify your Job Match email address"
    msg["From"] = settings.smtp_from
    msg["To"] = to_email

    name = full_name or "there"

    text_body = (
        f"Hi {name},\n\n"
        "Please verify your email address to unlock all Job Match features.\n\n"
        f"Verification link: {verify_url}\n\n"
        "This link expires in 24 hours.\n\n"
        "If you did not create a Job Match account, you can safely ignore this email.\n\n"
        "— The Job Match Team"
    )

    html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
  <h2 style="color: #5C6BC0;">Verify your email address</h2>
  <p>Hi {name},</p>
  <p>Please verify your email address to unlock all Job Match features including swiping and applying to jobs.</p>
  <p style="text-align: center; margin: 32px 0;">
    <a href="{verify_url}"
       style="background-color: #5C6BC0; color: #ffffff; padding: 14px 28px;
              text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
      Verify Email Address
    </a>
  </p>
  <p style="font-size: 13px; color: #666;">
    Or copy this link into your browser:<br>
    <a href="{verify_url}" style="color: #5C6BC0;">{verify_url}</a>
  </p>
  <p style="font-size: 13px; color: #666;">This link expires in 24 hours.</p>
  <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
  <p style="font-size: 12px; color: #999;">
    If you did not create a Job Match account, you can safely ignore this email.
  </p>
</body>
</html>"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    return msg


def _send_smtp(to_email: str, msg: MIMEMultipart) -> None:
    """Blocking SMTP send — run via asyncio.to_thread."""
    if settings.smtp_tls:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
        server.ehlo()
        server.starttls()
    else:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port)

    if settings.smtp_user:
        server.login(settings.smtp_user, settings.smtp_password)

    server.sendmail(settings.smtp_from, to_email, msg.as_string())
    server.quit()


def _build_password_reset_email(to_email: str, full_name: str, reset_url: str) -> MIMEMultipart:
    """Build a MIME message for the password reset email."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset your Job Match password"
    msg["From"] = settings.smtp_from
    msg["To"] = to_email

    name = full_name or "there"

    text_body = (
        f"Hi {name},\n\n"
        "We received a request to reset your Job Match password.\n\n"
        f"Reset link: {reset_url}\n\n"
        "This link expires in 1 hour.\n\n"
        "If you did not request a password reset, you can safely ignore this email.\n\n"
        "— The Job Match Team"
    )

    html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
  <h2 style="color: #5C6BC0;">Reset your password</h2>
  <p>Hi {name},</p>
  <p>We received a request to reset your Job Match password. Click the button below to choose a new password.</p>
  <p style="text-align: center; margin: 32px 0;">
    <a href="{reset_url}"
       style="background-color: #5C6BC0; color: #ffffff; padding: 14px 28px;
              text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
      Reset Password
    </a>
  </p>
  <p style="font-size: 13px; color: #666;">
    Or copy this link into your browser:<br>
    <a href="{reset_url}" style="color: #5C6BC0;">{reset_url}</a>
  </p>
  <p style="font-size: 13px; color: #666;">This link expires in 1 hour.</p>
  <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
  <p style="font-size: 12px; color: #999;">
    If you did not request a password reset, you can safely ignore this email.
    Your password will not be changed.
  </p>
</body>
</html>"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    return msg


async def send_password_reset_email(to_email: str, full_name: str, token: str) -> None:
    """Send a password reset email asynchronously.

    If SMTP is not configured, the reset URL is logged instead so
    developers can test the flow without an email provider.
    """
    reset_url = f"{settings.frontend_url}/reset-password?token={token}"

    if not settings.smtp_host:
        logger.info(
            "SMTP not configured — password reset link for %s: %s",
            to_email,
            reset_url,
        )
        return

    try:
        msg = _build_password_reset_email(to_email, full_name, reset_url)
        await asyncio.to_thread(_send_smtp, to_email, msg)
        logger.info("Password reset email sent to %s", to_email)
    except Exception:
        logger.exception("Failed to send password reset email to %s", to_email)


async def send_verification_email(to_email: str, full_name: str, token: str) -> None:
    """Send a verification email asynchronously.

    If SMTP is not configured, the verification URL is logged instead so
    developers can confirm accounts without an email provider.
    """
    verify_url = f"{settings.frontend_url}/verify-email?token={token}"

    if not settings.smtp_host:
        # Development mode: log the link instead of sending
        logger.info(
            "SMTP not configured — email verification link for %s: %s",
            to_email,
            verify_url,
        )
        return

    try:
        msg = _build_verification_email(to_email, full_name, verify_url)
        await asyncio.to_thread(_send_smtp, to_email, msg)
        logger.info("Verification email sent to %s", to_email)
    except Exception:
        logger.exception("Failed to send verification email to %s", to_email)
