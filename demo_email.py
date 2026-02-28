# -*- coding: utf-8 -*-
"""
Quick demo — sends a Welcome email + a Price Drop email to your inbox.
Usage:  python demo_email.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from types import SimpleNamespace
from app.watchlist.email_sender import send_welcome_email, send_price_drop_email
from app.config import settings

TARGET = settings.smtp_user  # sends to yourself

print(f"📧  Sending demo emails to: {TARGET}")
print(f"    SMTP host : {settings.smtp_host}:{settings.smtp_port}")
print(f"    SMTP user : {settings.smtp_user}")
print()

# ── 1. Welcome Email ─────────────────────────────────────────────────────────
print("1️⃣  Sending Welcome email …", end=" ", flush=True)
send_welcome_email(
    user_email=TARGET,
    product_title="Samsung Galaxy S24 Ultra 256GB — Titanium Black",
    threshold=10.0,
)
print("✅  Done!")

# ── 2. Price Drop Email ──────────────────────────────────────────────────────
print("2️⃣  Sending Price Drop alert …", end=" ", flush=True)

mock_item = SimpleNamespace(
    product_title="Samsung Galaxy S24 Ultra 256GB — Titanium Black",
    site="Amazon India",
    product_url="https://www.amazon.in/dp/B0CS5XXXXX",
    thumbnail_url="https://m.media-amazon.com/images/I/71lFKIRNgjL._SL1500_.jpg",
    alert_threshold=10.0,
)

send_price_drop_email(
    user_email=TARGET,
    item=mock_item,
    old_price=139999.0,   # saved price
    new_price=119999.0,   # new lower price  (14.3% drop)
    drop_pct=14.3,
)
print("✅  Done!")

print()
print(f"🎉  Check your inbox at {TARGET} — you should see 2 emails!")
