#!/usr/bin/env python3
"""Data masking and PII sanitization utilities for live demo."""
import re

def mask_email(email: str) -> str:
    """Mask email: jg0592@gmail.com -> j***2@gmail.com"""
    if not email or "@" not in email:
        return email
    user, domain = email.split("@", 1)
    if len(user) <= 2:
        masked_user = user[0] + "*"
    else:
        masked_user = user[0] + "*" * (len(user) - 2) + user[-1]
    return f"{masked_user}@{domain}"

def mask_card(card_last4: str) -> str:
    """Mask card last 4: 8143 -> **43"""
    if not card_last4:
        return "****"
    s = str(card_last4).strip()
    if len(s) == 4:
        return f"**{s[2:]}"
    return "****"

def mask_pii_text(text: str) -> str:
    """Mask personal identifiers, names, phone numbers, and accounts in free text."""
    if not text:
        return ""
    # Mask emails
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', lambda m: mask_email(m.group(0)), text)
    # Mask names like JAIME ANTONIO GARCIA or Jaime Garcia
    text = re.sub(r'\b(JAIME\s+ANTONIO\s+GARCIA|JAIME\s+GARCIA|Jaime\s+Garc[ií]a)\b', 'J**** G****', text, flags=re.IGNORECASE)
    # Mask bank account numbers
    text = re.sub(r'\b(CUENTA\s+(?:DE\s+AHORRO\s+)?)(X?\d{4,12})\b', r'\1****', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(CTA\s*(?:CTE|AH)\s*[:#]?\s*)(X?\d{4,12})\b', r'\1****', text, flags=re.IGNORECASE)
    # Mask phone numbers like 2212-2000
    text = re.sub(r'\b\d{4}-\d{4}\b', '****-****', text)
    # Mask authorization codes
    text = re.sub(r'\b(AUT|AUTORIZACI[OÓ]N)\s*[:#]?\s*([A-Z0-9]{4,10})\b', r'\1: ******', text, flags=re.IGNORECASE)
    return text

def mask_silver_record(rec: dict) -> dict:
    """Create a masked copy of a silver record for live presentation."""
    masked = dict(rec)
    if "card_last4" in masked:
        masked["card_last4"] = mask_card(masked["card_last4"])
    if "merchant" in masked:
        masked["merchant"] = mask_pii_text(str(masked["merchant"]))
    return masked
