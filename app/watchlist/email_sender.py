# -*- coding: utf-8 -*-
"""
Email sender for price drop alerts and watchlist confirmation emails.

Uses Python built-in smtplib only — no external email library.
SMTP_PASSWORD must be a Gmail App Password (NOT regular password).

Setup:
  Gmail → Google Account → Security → 2-Step Verification → ON
  → App Passwords → Generate → Copy 16-char password → .env SMTP_PASSWORD
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# AI-GENERATED TEXT HELPER
# ═══════════════════════════════════════════════════════════════════════════════


def _generate_ai_message(product_title: str, site: str, price: float, threshold: float) -> str:
    """Generate a short AI description for the watchlist confirmation email.

    Uses Groq synchronously (called in executor). Falls back to static text.
    """
    try:
        from groq import Groq
        if not settings.groq_api_key:
            raise ValueError("No API key")

        client = Groq(api_key=settings.groq_api_key)
        prompt = (
            f"Write a short (2-3 sentences), friendly, enthusiastic message for a user who just "
            f"added a product to their price watchlist. Product: '{product_title}' from {site} "
            f"at ₹{price:,.0f}. They'll be notified when the price drops by {threshold}% or more. "
            f"Be conversational, mention the specific product briefly, and reassure them that "
            f"the AI monitors prices 24/7. Do NOT use markdown. Do NOT use emojis. "
            f"Keep it under 60 words."
        )
        response = client.chat.completions.create(
            model=settings.groq_fast_model or "llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a helpful price comparison assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=120,
        )
        text = response.choices[0].message.content.strip()
        if text and len(text) > 10:
            return text
    except Exception as e:
        logger.warning("AI message generation failed, using fallback: %s", e)

    # Fallback
    return (
        f"Great choice! We've added {product_title[:50]} to your watchlist. "
        f"Our AI monitors prices around the clock across all major Indian marketplaces. "
        f"You'll be the first to know when the price drops by {threshold:.0f}% or more."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE DROP EMAIL
# ═══════════════════════════════════════════════════════════════════════════════


def send_price_drop_email(
    user_email: str,
    item,
    old_price: float,
    new_price: float,
    drop_pct: float,
) -> None:
    """Send price drop notification email.

    NOT async — smtplib is synchronous.
    Called via: asyncio.get_event_loop().run_in_executor(None, ...)

    Never raises exceptions — scheduler must not crash.
    """
    try:
        savings = old_price - new_price

        subject = (
            f"\U0001f525 Price Drop! {item.product_title[:50]}"
            f" \u2014 Save \u20b9{savings:,.0f}"
        )

        thumbnail_html = ""
        if getattr(item, "thumbnail_url", None):
            thumbnail_html = (
                f'<img src="{item.thumbnail_url}" alt="" '
                f'style="max-width:120px;max-height:120px;border-radius:8px;'
                f'object-fit:contain;margin-right:16px;" />'
            )

        title_display = item.product_title
        if len(title_display) > 60:
            title_display = title_display[:57] + "..."

        html_body = f"""
        <div style="max-width:520px;margin:0 auto;font-family:'Segoe UI',Arial,sans-serif;">
            <!-- Header -->
            <div style="background:#0a0e17;padding:20px 24px;border-radius:12px 12px 0 0;text-align:center;">
                <h1 style="color:#f1f5f9;font-size:20px;margin:0;">
                    \U0001f4b0 PriceCompare AI
                </h1>
                <p style="color:#94a3b8;font-size:13px;margin:4px 0 0 0;">
                    Your price alert was triggered!
                </p>
            </div>

            <!-- Product -->
            <div style="background:#111827;padding:20px 24px;">
                <div style="display:flex;align-items:center;">
                    {thumbnail_html}
                    <div>
                        <p style="color:#f1f5f9;font-size:16px;font-weight:600;margin:0 0 6px 0;">
                            {title_display}
                        </p>
                        <span style="display:inline-block;background:#1e3a5f;color:#38bdf8;
                                     padding:3px 10px;border-radius:12px;font-size:12px;">
                            {item.site}
                        </span>
                    </div>
                </div>
            </div>

            <!-- Price Comparison -->
            <div style="background:#1a2235;padding:20px 24px;">
                <table style="width:100%;border-collapse:collapse;">
                    <tr>
                        <td style="color:#94a3b8;font-size:13px;padding:6px 0;">Was:</td>
                        <td style="color:#94a3b8;font-size:16px;text-decoration:line-through;
                                   text-align:right;padding:6px 0;">
                            \u20b9{old_price:,.0f}
                        </td>
                    </tr>
                    <tr>
                        <td style="color:#10b981;font-size:13px;padding:6px 0;font-weight:600;">
                            NOW:
                        </td>
                        <td style="color:#10b981;font-size:22px;font-weight:700;
                                   text-align:right;padding:6px 0;">
                            \u20b9{new_price:,.0f}
                        </td>
                    </tr>
                    <tr>
                        <td colspan="2" style="padding:8px 0 0 0;">
                            <div style="background:#166534;color:#bbf7d0;padding:6px 12px;
                                        border-radius:8px;font-size:13px;font-weight:600;
                                        text-align:center;">
                                You save \u20b9{savings:,.0f} ({drop_pct:.1f}% off)
                            </div>
                        </td>
                    </tr>
                </table>
            </div>

            <!-- CTA Button -->
            <div style="background:#1a2235;padding:0 24px 24px 24px;text-align:center;">
                <a href="{item.product_url}"
                   style="display:inline-block;background:linear-gradient(135deg,#3b82f6,#8b5cf6);
                          color:#fff;text-decoration:none;padding:12px 32px;border-radius:24px;
                          font-size:15px;font-weight:600;letter-spacing:0.5px;">
                    VIEW DEAL \u2192
                </a>
            </div>

            <!-- Footer -->
            <div style="background:#0a0e17;padding:16px 24px;border-radius:0 0 12px 12px;
                        text-align:center;">
                <p style="color:#64748b;font-size:12px;margin:0;">
                    You saved this product on PriceCompare AI.
                </p>
                <p style="color:#64748b;font-size:12px;margin:4px 0 0 0;">
                    Alert threshold was set to {item.alert_threshold}% drop.
                </p>
            </div>
        </div>
        """

        _send_smtp(user_email, subject, html_body)
        logger.info("Price drop email sent to %s for %s", user_email, item.product_title[:40])

    except Exception as e:
        logger.error("Price drop email failed for %s: %s", user_email, e)


# ═══════════════════════════════════════════════════════════════════════════════
# WATCHLIST ADDED — AI-GENERATED CONFIRMATION EMAIL (sent on EVERY save)
# ═══════════════════════════════════════════════════════════════════════════════


def send_watchlist_added_email(
    user_email: str,
    product_title: str,
    site: str,
    saved_price: float,
    threshold: float,
    product_url: str = "",
    thumbnail_url: str = "",
) -> None:
    """Send an AI-generated confirmation email when user adds product to watchlist.

    Sent on EVERY save — not just the first time.
    NOT async. Never raises exceptions.
    """
    try:
        # Generate AI message
        ai_message = _generate_ai_message(product_title, site, saved_price, threshold)
        logger.info("AI message generated for %s", product_title[:40])

        title_display = product_title
        if len(title_display) > 65:
            title_display = title_display[:62] + "..."

        price_display = f"₹{saved_price:,.0f}" if saved_price else "N/A"

        thumbnail_html = ""
        if thumbnail_url:
            thumbnail_html = f"""
                <div style="text-align:center;padding:16px 0 8px 0;">
                    <img src="{thumbnail_url}" alt=""
                         style="max-width:140px;max-height:140px;border-radius:10px;
                                object-fit:contain;background:#fff;padding:8px;" />
                </div>
            """

        cta_html = ""
        if product_url:
            cta_html = f"""
                <div style="text-align:center;padding:0 0 8px 0;">
                    <a href="{product_url}"
                       style="display:inline-block;background:linear-gradient(135deg,#3b82f6,#8b5cf6);
                              color:#fff;text-decoration:none;padding:11px 28px;border-radius:24px;
                              font-size:14px;font-weight:600;letter-spacing:0.3px;">
                        VIEW PRODUCT →
                    </a>
                </div>
            """

        subject = f"🛒 Added to Watchlist — {title_display}"

        html_body = f"""
        <div style="max-width:540px;margin:0 auto;font-family:'Segoe UI',Arial,sans-serif;
                    background:#0a0e17;border-radius:14px;overflow:hidden;">

            <!-- Header -->
            <div style="background:linear-gradient(135deg,#0a0e17,#1a2235);
                        padding:24px 28px;text-align:center;
                        border-bottom:1px solid rgba(148,163,184,0.1);">
                <h1 style="color:#f1f5f9;font-size:21px;margin:0 0 4px 0;font-weight:700;">
                    💰 PriceCompare AI
                </h1>
                <p style="color:#94a3b8;font-size:13px;margin:0;">
                    Product added to your watchlist
                </p>
            </div>

            <!-- Product Card -->
            <div style="background:#111827;padding:20px 28px;">
                {thumbnail_html}
                <div style="background:#1a2235;border:1px solid rgba(148,163,184,0.1);
                            border-radius:12px;padding:16px;margin-bottom:16px;">
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;
                                     background:#10b981;"></span>
                        <span style="color:#94a3b8;font-size:12px;text-transform:uppercase;
                                     letter-spacing:0.06em;font-weight:600;">
                            {site}
                        </span>
                    </div>
                    <p style="color:#f1f5f9;font-size:15px;font-weight:600;line-height:1.4;
                              margin:0 0 10px 0;">
                        {title_display}
                    </p>
                    <div style="display:flex;align-items:center;gap:12px;">
                        <span style="color:#10b981;font-size:20px;font-weight:800;">
                            {price_display}
                        </span>
                        <span style="display:inline-block;background:rgba(59,130,246,0.15);
                                     color:#60a5fa;padding:3px 10px;border-radius:20px;
                                     font-size:12px;font-weight:600;">
                            Alert at -{threshold:.0f}%
                        </span>
                    </div>
                </div>

                {cta_html}
            </div>

            <!-- AI-Generated Message -->
            <div style="background:linear-gradient(135deg,#1a2235,#111827);
                        padding:20px 28px;border-top:1px solid rgba(148,163,184,0.08);">
                <div style="display:flex;align-items:flex-start;gap:10px;">
                    <span style="display:inline-block;background:linear-gradient(135deg,#3b82f6,#8b5cf6);
                                 color:#fff;width:28px;height:28px;border-radius:8px;
                                 text-align:center;line-height:28px;font-size:14px;flex-shrink:0;">
                        ✨
                    </span>
                    <div>
                        <p style="color:#60a5fa;font-size:11px;font-weight:700;
                                  text-transform:uppercase;letter-spacing:0.08em;margin:0 0 6px 0;">
                            AI Assistant says
                        </p>
                        <p style="color:#cbd5e1;font-size:14px;line-height:1.6;margin:0;
                                  font-style:italic;">
                            "{ai_message}"
                        </p>
                    </div>
                </div>
            </div>

            <!-- Tracking Info -->
            <div style="background:#0a0e17;padding:18px 28px;
                        border-top:1px solid rgba(148,163,184,0.08);">
                <table style="width:100%;border-collapse:collapse;">
                    <tr>
                        <td style="color:#94a3b8;font-size:12px;padding:4px 0;">
                            🔍 Price checks
                        </td>
                        <td style="color:#f1f5f9;font-size:12px;text-align:right;padding:4px 0;">
                            Every {settings.watchlist_check_interval_hours} hours
                        </td>
                    </tr>
                    <tr>
                        <td style="color:#94a3b8;font-size:12px;padding:4px 0;">
                            🔔 Alert threshold
                        </td>
                        <td style="color:#f1f5f9;font-size:12px;text-align:right;padding:4px 0;">
                            {threshold:.0f}% price drop
                        </td>
                    </tr>
                    <tr>
                        <td style="color:#94a3b8;font-size:12px;padding:4px 0;">
                            🏪 Marketplaces
                        </td>
                        <td style="color:#f1f5f9;font-size:12px;text-align:right;padding:4px 0;">
                            12 Indian stores
                        </td>
                    </tr>
                </table>
            </div>

            <!-- Footer -->
            <div style="background:#0a0e17;padding:14px 28px 20px;text-align:center;
                        border-top:1px solid rgba(148,163,184,0.06);">
                <p style="color:#64748b;font-size:11px;margin:0;line-height:1.5;">
                    PriceCompare AI — AI-powered price comparison across India<br/>
                    Visit your Watchlist in the app anytime to manage alerts.
                </p>
            </div>
        </div>
        """

        _send_smtp(user_email, subject, html_body)
        logger.info(
            "Watchlist added email sent to %s for %s",
            user_email, product_title[:40],
        )

    except Exception as e:
        logger.error("Watchlist added email failed for %s: %s", user_email, e)


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY WELCOME EMAIL (kept for backward compat)
# ═══════════════════════════════════════════════════════════════════════════════


def send_welcome_email(user_email: str, product_title: str, threshold: float) -> None:
    """Send welcome email when user saves their FIRST product.

    NOT async. Never raises exceptions.
    """
    try:
        title_short = product_title[:40] if len(product_title) > 40 else product_title
        subject = f"\u2705 Price alerts activated for {title_short}"

        html_body = f"""
        <div style="max-width:520px;margin:0 auto;font-family:'Segoe UI',Arial,sans-serif;">
            <div style="background:#0a0e17;padding:20px 24px;border-radius:12px 12px 0 0;
                        text-align:center;">
                <h1 style="color:#f1f5f9;font-size:20px;margin:0;">
                    \U0001f4b0 PriceCompare AI
                </h1>
            </div>
            <div style="background:#111827;padding:24px;">
                <h2 style="color:#10b981;font-size:18px;margin:0 0 12px 0;">
                    \u2705 Your price alert is set up!
                </h2>
                <p style="color:#f1f5f9;font-size:14px;line-height:1.6;">
                    We will email you when <strong>{product_title}</strong>
                    drops by <strong>{threshold}%</strong> or more.
                </p>
                <p style="color:#94a3b8;font-size:13px;line-height:1.6;margin-top:12px;">
                    We check prices every {settings.watchlist_check_interval_hours} hours
                    across all supported marketplaces.
                </p>
                <p style="color:#94a3b8;font-size:13px;margin-top:16px;">
                    Check your saved products anytime at the \U0001f49b Watchlist
                    tab in the app.
                </p>
            </div>
            <div style="background:#0a0e17;padding:16px 24px;border-radius:0 0 12px 12px;
                        text-align:center;">
                <p style="color:#64748b;font-size:12px;margin:0;">
                    PriceCompare AI — AI-powered price comparison across India
                </p>
            </div>
        </div>
        """

        _send_smtp(user_email, subject, html_body)
        logger.info("Welcome email sent to %s", user_email)

    except Exception as e:
        logger.error("Welcome email failed for %s: %s", user_email, e)


# ═══════════════════════════════════════════════════════════════════════════════
# SMTP HELPER
# ═══════════════════════════════════════════════════════════════════════════════


def _send_smtp(to_email: str, subject: str, html_body: str) -> None:
    """Send an email via SMTP. Raises on failure (caller must handle)."""
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP credentials not configured — email skipped")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_user}>"
    msg["To"] = to_email

    msg.attach(MIMEText(html_body, "html"))

    server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
    server.starttls()
    server.login(settings.smtp_user, settings.smtp_password)
    server.sendmail(settings.smtp_user, to_email, msg.as_string())
    server.quit()
