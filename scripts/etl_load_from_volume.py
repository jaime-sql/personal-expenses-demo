# Databricks notebook source
# MAGIC %md
# MAGIC # personal_expenses — ETL: Gmail bronze -> silver (daily)
# MAGIC
# MAGIC - `bronze_mail_alerts` = ALL `/Volumes/workspace/personal_expenses/landing/gmail/*.jsonl` (dedupe by message_id, latest ingested_at wins).
# MAGIC   New files `inc_YYYYMMDD_HHMM.jsonl` are dropped daily at 6:30 SV by `daily_gmail_ingest.py` (raw rows, no parsing).
# MAGIC - `silver_charges` = legacy `landing/silver/silver_charges.jsonl` (history through 2026-10-26)
# MAGIC   UNION bronze parsed here (same rules as alert_parser.py).
# MAGIC   Legacy wins when charge_id collides. A broad-NAVARRA collapse (coffee or any other
# MAGIC   Navarra merchant stored as AUTO TALLER NAVARRA) is corrected in place and keeps its
# MAGIC   historical charge_id, so a rebuild cannot insert a second row for the same purchase.
# MAGIC   Bronze is re-parsed even when its message_id is already in legacy, so that correction
# MAGIC   can see the raw merchant. Other legacy fields stay.
# MAGIC   landing/silver may repeat a charge_id. Those copies collapse to one row: the copy
# MAGIC   that matches the charge already in silver_charges, else the earliest landing row.
# MAGIC   Distinct charge_ids are kept and their amounts are not added together.
# MAGIC - Freshness: FAIL if newest bronze received_at > 3 days old; WARNING only if max charge_date_sv > 2 days old.
# MAGIC
# MAGIC Widget: `dry_run` = false|true

# COMMAND ----------

dbutils.widgets.text("dry_run", "false")
DRY_RUN = dbutils.widgets.get("dry_run").strip().lower() in ("1", "true", "yes", "y")
print(f"dry_run={DRY_RUN}")
CATALOG, SCHEMA = "workspace", "personal_expenses"
BRONZE_PATH = "/Volumes/workspace/personal_expenses/landing/gmail/"
SILVER_PATH = "/Volumes/workspace/personal_expenses/landing/silver/"
MAP_TABLE = f"{CATALOG}.{SCHEMA}.map_merchant_category"
BRONZE_TABLE = f"{CATALOG}.{SCHEMA}.bronze_mail_alerts"
SILVER_TABLE = f"{CATALOG}.{SCHEMA}.silver_charges"
PARSE_FROM_SV = "2026-10-25"   # only parse bronze received on/after this SV date (legacy silver covers earlier history)
FAIL_BRONZE_DAYS = 3
WARN_CHARGE_DAYS = 2

# COMMAND ----------

# --- alert_parser: bank alert email -> silver charge (shared by daily_gmail_ingest.py and the ETL notebook) ---
# Category/merchant/movement rules are copied verbatim from build_and_load.py.
# NAVARRA is not a merchant. Only AUTO TALLER NAVARRA is the workshop.
# COFFE CUP / COFFEE CUP stay their own merchant and are restaurants.
# FEE must not match inside COFFEE. charge_id stays a hash of the normalized merchant;
# reconcile_charges corrects a collapsed historical row in place so the id does not fork.
import re, hashlib, html
from datetime import datetime, timedelta, timezone

SEED = [
    ("SIMAN", "shopping"), ("VIDRI", "shopping"), ("AMAZON", "shopping"), ("TEMU", "shopping"),
    ("PAYPAL *TEMU", "shopping"), ("ROSS", "shopping"), ("TJ MAXX", "shopping"), ("N1COVIDRI", "shopping"),
    ("DOLLARCITY", "shopping"), ("PRICE SMART", "shopping"), ("WALMART", "groceries"),
    ("SELECTOS", "groceries"), ("SUPER SELECTOS", "groceries"), ("COSTCO", "groceries"),
    ("PUMA", "fuel"), ("PUMA ENERGY", "fuel"), ("PUMA PALERMO", "fuel"),
    ("UBER", "transport"), ("UBR", "transport"), ("AUTO TALLER NAVARRA", "transport"),
    ("PARQUEO", "transport"),
    ("AVIANCA", "travel"), ("VOLARIS", "travel"), ("DAYS INN", "travel"),
    ("PEDIDOSYA", "restaurants"), ("CHINA WOK", "restaurants"), ("CAMPERO", "restaurants"),
    ("POLLO CAMPERO", "restaurants"), ("MC DONALD", "restaurants"), ("LLAO LLAO", "restaurants"),
    ("TOROGOZ", "transfers"), ("BANCA DIGITAL", "transfers"), ("TRANSFER365", "transfers"),
    ("DISNEY", "subscriptions"), ("HBO", "subscriptions"), ("CLOUDWAYS", "subscriptions"),
    ("GOOGLE", "subscriptions"), ("NETFLIX", "subscriptions"), ("SPOTIFY", "subscriptions"),
    ("FONDO SOCIAL VIVIENDA", "utilities"), ("FSV", "utilities"), ("ANDA", "utilities"),
    ("CAESS", "utilities"), ("DIGICEL", "utilities"), ("CLARO", "utilities"), ("TIGO", "utilities"),
    ("DEL SUR", "utilities"), ("CIA ALU", "utilities"),
    ("COLEGIOS MARISTAS", "education"), ("INSTITUTEEL", "education"), ("INSTITUTE EL", "education"),
    ("CNR", "other"), ("FCIA", "health"), ("FARMACIA", "health"), ("HOSPITAL", "health"),
]
KEYWORD_ORDER = [
    ("transfers", ["TRANSFER365", "TOROGOZ", "BANCA DIGITAL", "TRANSFERENCIA"]),
    ("fees", ["COMISION", "FEE", "MORA", "INTERES"]),
    ("fuel", ["PUMA", "TEXACO", "SHELL", "GASOLIN"]),
    ("utilities", ["ANDA", "CAESS", "FSV", "FONDO SOCIAL", "CLARO", "TIGO", "DIGICEL", "DEL SUR", "CIA ALU", "AES"]),
    ("education", ["COLEGIOS MARISTAS", "INSTITUTE", "UNIVERSIDAD", "UJMD"]),
    ("subscriptions", ["DISNEY", "HBO", "NETFLIX", "SPOTIFY", "CLOUDWAYS", "GOOGLE *", "APPLE.COM", "MICROSOFT"]),
    ("groceries", ["SELECTOS", "WALMART", "COSTCO", "PRICE SMART", "SUPERMERCADO"]),
    ("transport", ["UBER", "UBR ", "PARQUEO", "AUTO TALLER", "TAXI"]),
    ("travel", ["AVIANCA", "VOLARIS", "COPA", "HOTEL", "DAYS INN", "AIRBNB"]),
    ("health", ["FCIA", "FARMACIA", "HOSPITAL", "CLINICA", "LABORATORIO", "MEDICO"]),
    ("restaurants", ["PEDIDOSYA", "CHINA WOK", "CAMPERO", "MC DONALD", "LLAO LLAO", "RESTAURANT", "PIZZA", "STARBUCKS", "TIPICOS", "SAZON"]),
    ("shopping", ["SIMAN", "VIDRI", "AMAZON", "TEMU", "ROSS", "TJ MAXX", "DOLLARCITY", "N1CO", "PAYPAL"]),
]
CARD_PAY_MARKERS = ["PAGO TARJETA", "PAGO DE TARJETA", "ABONO A TARJETA", "PAGO TC", "PAYMENT THANK YOU", "PAYMENT THANK"]
REFUND_MARKERS = ["REEMBOLSO", "REFUND", "CARGO REVERTIDO", "REVERSI", "ANULACI", "DEVOLUCI",
                  "CREDIT ADJUSTMENT", "AJUSTE DE CREDITO", "AJUSTE DE CRÉDITO"]
ALLOWLIST = {
    "soluciones@promericaotp.com.sv": "Promerica",
    "alertas_tarjeta@credicomer.com.sv": "Credicomer",
    "notificaciones_clientes@credicomer.com.sv": "Credicomer",
    "noreply@bi.com.sv": "BI",
    "notificaciones@bancocuscatlan.com": "Cuscatlán",
    "info@baccredomatic.com": "BAC",
}
WORKSHOP_NORM = "AUTO TALLER NAVARRA"
# Gmail API ids are hex, shorter than the 32-char charge_id hash. A hit is necessary but not
# sufficient: the id also has to be on bronze with a real thread_id (see source_email_link).
GMAIL_ID_PATTERN = r"^[0-9a-fA-F]{15,20}$"
_GMAIL_ID = re.compile(GMAIL_ID_PATTERN)
# Static Gmail URL. The account is percent-encoded once (%40). The only substituted
# value is the hex thread id, which URL-encoding does not change.
GMAIL_LINK_TEMPLATE = "https://mail.google.com/mail/?authuser=jg0592%40gmail.com#all/{{source_thread_id}}"
_COFFEE_CUP = re.compile(r"\bCOFFEE?\s+CUP\b")

def _prep_merchant(m):
    return re.sub(r"\s+", " ", (m or "").strip().upper())

def is_coffee_cup(merchant):
    """COFFE CUP or COFFEE CUP, as a phrase. CUPCAKE does not match."""
    return _COFFEE_CUP.search(_prep_merchant(merchant)) is not None

def is_auto_taller_navarra(merchant):
    m = _prep_merchant(merchant)
    return "AUTO TALLER" in m and "NAVARRA" in m and not is_coffee_cup(m)

def is_real_gmail_id(value):
    return bool(value) and _GMAIL_ID.fullmatch(str(value).strip()) is not None

def gmail_alert_url(thread_id):
    """Open this mailbox's Gmail thread. None when the id is not a real Gmail id."""
    if not is_real_gmail_id(thread_id):
        return None
    return GMAIL_LINK_TEMPLATE.replace("{{source_thread_id}}", str(thread_id).strip())

def source_email_link(message_id, thread_id, in_bronze):
    """('email', url) only when bronze has this message and both ids are real Gmail ids.

    Synthetic historical ids, and silver rows with no bronze thread, are ('unavailable', None).
    """
    if in_bronze and is_real_gmail_id(message_id) and is_real_gmail_id(thread_id):
        return "email", gmail_alert_url(thread_id)
    return "unavailable", None

def source_email_link_for_group(rows):
    """One grid row that covers several charges.

    Same real thread for every charge → that link. Otherwise unavailable,
    so a grouped cell never points at one of several emails.
    `rows` items are (message_id, thread_id, in_bronze).
    """
    rows = list(rows)
    if len(rows) == 1:
        return source_email_link(*rows[0])
    links = [source_email_link(*r) for r in rows]
    urls = {url for label, url in links if url}
    if len(rows) > 1 and len(urls) == 1 and all(label == "email" for label, _ in links):
        return "email", next(iter(urls))
    return "unavailable", None

def _kw_in(kw, text):
    if kw == "FEE":
        # "FEE" is the last three letters of "COFFEE". Drop that word, then look.
        # Other FEE hits (FEE, FEEDER, OVERDRAFT FEE) stay as they were.
        text = re.sub(r"COFFEE", "", text)
    return kw in text

def norm_merchant(m):
    m = _prep_merchant(m)
    if m.startswith("SIMAN"): return "SIMAN"
    if "SELECTOS" in m: return "SELECTOS"
    if m.startswith("UBER") or m.startswith("UBR"): return "UBER"
    if "HBO" in m: return "HBO"
    if "TEMU" in m: return "TEMU"
    if m.startswith("PUMA"): return "PUMA"
    if "AVIANCA" in m: return "AVIANCA"
    if "VOLARIS" in m: return "VOLARIS"
    if "CAMPERO" in m: return "POLLO CAMPERO"
    if "DISNEY" in m: return "DISNEY"
    if "CLOUDWAYS" in m: return "CLOUDWAYS"
    if "FONDO SOCIAL" in m or m.startswith("FSV"): return "FONDO SOCIAL VIVIENDA"
    if "COLEGIOS MARISTAS" in m: return "COLEGIOS MARISTAS"
    # Coffee that shares a place-name with the workshop keeps the bank's text.
    if is_coffee_cup(m): return m[:80]
    if is_auto_taller_navarra(m): return WORKSHOP_NORM
    if m.startswith("CNR") or " CNR " in f" {m} ": return "CNR"
    return m[:80]

def classify(merchant, existing=None):
    # This merchant family is decided from the text. A stale transport/fees
    # label must not stick. Every other merchant still honors `existing`.
    if is_coffee_cup(merchant):
        return "restaurants"
    if is_auto_taller_navarra(merchant):
        return "transport"
    if existing and existing not in ("", "other"):
        return existing
    m = _prep_merchant(merchant)
    for cat, kws in KEYWORD_ORDER:
        for kw in kws:
            if _kw_in(kw, m):
                return cat
    nm = norm_merchant(merchant)
    for pat, cat in SEED:
        if pat in nm or nm.startswith(pat):
            return cat
    return existing or "other"

def movement_type(merchant, category=None, subject=""):
    blob = f"{merchant or ''} {subject or ''} {category or ''}".upper()
    if any(k in blob for k in REFUND_MARKERS): return "refund"
    if any(k in blob for k in CARD_PAY_MARKERS): return "card_payment"
    if category == "transfers" or any(k in blob for k in ["TRANSFER365", "TOROGOZ", "BANCA DIGITAL", "TRANSFERENCIA"]):
        return "transfer"
    return "purchase"

def charge_id(bank, card, date, amount, merchant_norm):
    key = f"{bank}|{card}|{date}|{round(float(amount),2)}|{(merchant_norm or '')[:28]}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]

def bank_for_sender(frm):
    f = (frm or "").lower()
    for email, b in ALLOWLIST.items():
        if email in f:
            return email, b
    return None, None

SV = timezone(timedelta(hours=-6))
def _sv_date_from_received(ra):
    if not ra: return None
    try:
        d = datetime.fromisoformat(str(ra).replace("Z", "+00:00"))
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(SV).strftime("%Y-%m-%d")
    except Exception:
        return None

def _dmy(s):
    d, m, y = s.split("/"); return f"{y}-{int(m):02d}-{int(d):02d}"

def _amt(s):
    s = s.replace(",", "").strip()
    if s.startswith("."): s = "0" + s
    return round(float(s), 2)

def _clean(text):
    t = html.unescape(text or "")
    return re.sub(r"\s+", " ", t).strip()

def parse_alert(rec):
    """rec = bronze row dict. Returns a silver dict, or None if the email is not a money movement we count."""
    bank = rec.get("bank"); subj = _clean(rec.get("subject")).upper()
    t = _clean((rec.get("body_text") or "") + " " + (rec.get("snippet") or ""))
    U = t.upper()
    merchant = card = date = amount = None; forced_mt = None; cat_hint = None
    if bank == "Promerica" and "COMPRA REALIZADA" in U:
        m = re.search(r"Monto \$ ?([\d,]*\.?\d+) Comercio (.+?) Tarjeta de Cr\S+ [X\-]*(\d{4})", t, re.I)
        if m: amount, merchant, card = _amt(m.group(1)), m.group(2), m.group(3)
        d = re.search(r"Fecha y hora (\d{2}/\d{2}/\d{4})", t)
        if d: date = _dmy(d.group(1))
    elif bank == "Credicomer" and "ALERTA MONETARIA" in subj:
        m = re.search(r"tarjeta [\* ]*(\d{4}) Monto \$ ?([\d,]*\.?\d+) Comercio (.+?)(?: Fecha (\d{2}/\d{2}/\d{4})|$| En caso)", t, re.I)
        if m:
            card, amount, merchant = m.group(1), _amt(m.group(2)), m.group(3)
            if m.group(4): date = _dmy(m.group(4))
        d = re.search(r"Fecha (\d{2}/\d{2}/\d{4})", t)
        if d: date = _dmy(d.group(1))
    elif bank == "Credicomer" and subj.startswith("TRANSFERENCIA TRANSFER365") and "TRANSFERENCIA EXITOSA" in U:
        m = re.search(r"No\. Transacci\S+ \$ ?([\d,]*\.?\d+)", t)
        if m: amount, merchant, card, cat_hint = _amt(m.group(1)), "TRANSFER365", "", "transfers"
    elif bank == "Credicomer" and "PAGO DE TARJETA PROPIO" in subj:
        m = re.search(r"No\. Transacci\S+ \$ ?([\d,]*\.?\d+)", t)
        c = re.search(r"Tarjeta de cr\S+ \**(\d{4})", t, re.I)
        if m: amount, merchant, card, forced_mt = _amt(m.group(1)), "PAGO DE TARJETA PROPIA", (c.group(1) if c else ""), "card_payment"
        d = re.search(r"Fecha realizada (\d{2}/\d{2}/\d{4})", t)
        if d: date = _dmy(d.group(1))
    elif bank == "Credicomer" and "PAGO DE COLECTOR" in subj:
        m = re.search(r"No\. Transacci\S+ \$ ?([\d,]*\.?\d+)", t)
        n = re.search(r"Nombre de colector (.+?) NPE", t)
        o = re.search(r"Cuenta origen (\d+)", t)
        if m: amount, merchant, card = _amt(m.group(1)), (n.group(1) if n else "PAGO DE COLECTOR"), (o.group(1)[-4:] if o else "")
        d = re.search(r"Fecha realizada (\d{2}/\d{2}/\d{4})", t)
        if d: date = _dmy(d.group(1))
    elif bank == "BI" and "CONSUMO" in subj:
        m = re.search(r"transacci\S+ en (.+?) ?, de Tarjeta", t, re.I)
        a = re.search(r"Monto: ?([\d,]*\.?\d+)", t)
        c = re.search(r"Cuenta Or\S+ [\d\*\-]*(\d{4})", t)
        d = re.search(r"Fecha: ?(\d{2}/\d{2}/\d{4})", t)
        if m and a: merchant, amount, card = m.group(1), _amt(a.group(1)), (c.group(1) if c else "")
        if d: date = _dmy(d.group(1))
    elif bank == "BAC" and "COMPRA" in U:
        m = re.search(r"terminada en (\d{4}).*?Comercio Monto (.+?) ([\d,]*\.\d{2}) Fecha y hora (\d{4})/(\d{2})/(\d{2})", t, re.I)
        if m:
            card, merchant, amount = m.group(1), m.group(2), _amt(m.group(3))
            date = f"{m.group(4)}-{m.group(5)}-{m.group(6)}"
    elif bank == "Cuscatlán" and "COMPRA CON TARJETA" in subj:
        m = re.search(r"X*(\d{4}) por USD ([\d,]*\.?\d+) en (.+?) el d\S+ (\d{4}-\d{2}-\d{2})", t, re.I)
        if m: card, amount, merchant, date = m.group(1), _amt(m.group(2)), m.group(3), m.group(4)
    if amount is None or not merchant:
        return None
    merchant = re.sub(r"\s+", " ", merchant).strip()
    date = date or _sv_date_from_received(rec.get("received_at"))
    nm = norm_merchant(merchant)
    cat = classify(merchant, cat_hint)
    mt = forced_mt or movement_type(merchant, cat, rec.get("subject") or "")
    if cat == "transfers": mt = "transfer"
    return {
        "charge_id": charge_id(bank, card or "", date, amount, nm),
        "message_id": rec.get("message_id"),
        "charge_date_sv": date,
        "amount_usd": amount,
        "merchant": merchant,
        "merchant_norm": nm,
        "bank": bank,
        "card_last4": (card or "")[-4:],
        "category": cat,
        "movement_type": mt,
        "is_consumption": mt == "purchase",
        "currency": "USD",
        "raw_subject": (rec.get("subject") or "").strip()[:300],
    }

def _date_str(v):
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return str(v)[:10]

def _amount(v):
    return round(float(v or 0), 2)

def _natural_key(row):
    card = row.get("card_last4") or ""
    return (
        row.get("bank") or "",
        str(card)[-4:],
        _date_str(row.get("charge_date_sv")),
        _amount(row.get("amount_usd")),
    )

def _navarra_related(row):
    blob = _prep_merchant(f"{row.get('merchant') or ''} {row.get('merchant_norm') or ''}")
    return "NAVARRA" in blob or is_coffee_cup(row.get("merchant")) or is_auto_taller_navarra(row.get("merchant"))

def correct_stored_merchant(row):
    """Fix a stored row from its own merchant text. charge_id is not recomputed."""
    out = dict(row)
    raw = out.get("merchant") or ""
    if is_coffee_cup(raw):
        out["merchant_norm"] = norm_merchant(raw)
        out["category"] = "restaurants"
        return out
    if is_auto_taller_navarra(raw):
        out["merchant_norm"] = WORKSHOP_NORM
        out["category"] = "transport"
        return out
    # The bank text survived, but an older run stored the collapsed workshop label.
    if raw and (out.get("merchant_norm") or "").upper() == WORKSHOP_NORM and not is_auto_taller_navarra(raw):
        out["merchant_norm"] = norm_merchant(raw)
        out["category"] = classify(raw)
        return out
    return out

def _needs_merchant_correction(legacy, parsed):
    raw = legacy.get("merchant") or ""
    parsed_raw = parsed.get("merchant") or ""
    if is_coffee_cup(raw):
        return norm_merchant(raw) != (legacy.get("merchant_norm") or "") or legacy.get("category") != "restaurants"
    # A longer workshop description is the workshop, not a collapsed coffee charge.
    if is_auto_taller_navarra(raw) and _prep_merchant(raw) != WORKSHOP_NORM:
        return False
    collapsed = (legacy.get("merchant_norm") or "").upper() == WORKSHOP_NORM or _prep_merchant(raw) == WORKSHOP_NORM
    if not collapsed:
        return False
    if is_coffee_cup(parsed_raw):
        return True
    if "NAVARRA" in _prep_merchant(parsed_raw) and not is_auto_taller_navarra(parsed_raw):
        return True
    return False

def _can_attach(legacy, parsed):
    raw = legacy.get("merchant") or ""
    parsed_raw = parsed.get("merchant") or ""
    if is_coffee_cup(raw):
        return is_coffee_cup(parsed_raw)
    if is_auto_taller_navarra(raw) and _prep_merchant(raw) != WORKSHOP_NORM:
        return is_auto_taller_navarra(parsed_raw) and not is_coffee_cup(parsed_raw)
    if _prep_merchant(raw) == WORKSHOP_NORM or (legacy.get("merchant_norm") or "").upper() == WORKSHOP_NORM:
        return is_coffee_cup(parsed_raw) or is_auto_taller_navarra(parsed_raw) or "NAVARRA" in _prep_merchant(parsed_raw)
    return norm_merchant(raw) == (parsed.get("merchant_norm") or "") and bool(norm_merchant(raw))

def _merge_pair(legacy, parsed):
    """Keep the historical charge_id. Overlay merchant fields only for this correction."""
    out = dict(legacy)
    if _needs_merchant_correction(legacy, parsed):
        out["merchant"] = parsed.get("merchant") or out.get("merchant")
        out["merchant_norm"] = parsed.get("merchant_norm")
        out["category"] = parsed.get("category")
        if parsed.get("movement_type"):
            out["movement_type"] = parsed.get("movement_type")
        if parsed.get("is_consumption") is not None:
            out["is_consumption"] = parsed.get("is_consumption")
    if is_real_gmail_id(parsed.get("message_id")) and not is_real_gmail_id(out.get("message_id")):
        out["message_id"] = parsed.get("message_id")
    return out

def _dedupe_parsed(parsed_rows):
    """First parsed row wins when message_id or charge_id repeats.

    Rows with different charge_ids are all kept. This does not sum amounts.
    """
    out, seen_mid, seen_cid = [], set(), set()
    for row in parsed_rows:
        mid = (row.get("message_id") or "").strip()
        cid = row.get("charge_id") or ""
        if mid and mid in seen_mid:
            continue
        if cid and cid in seen_cid:
            continue
        if mid:
            seen_mid.add(mid)
        if cid:
            seen_cid.add(cid)
        out.append(dict(row))
    return out

def _live_match_score(row, live):
    """How closely this landing duplicate matches the row already in silver."""
    if not live:
        return 0
    score = 0
    if _amount(row.get("amount_usd")) == _amount(live.get("amount_usd")):
        score += 4
    if (row.get("merchant") or "") == (live.get("merchant") or ""):
        score += 2
    if (row.get("category") or "") == (live.get("category") or ""):
        score += 1
    return score

def _collapse_duplicate_charge_ids(rows, live_rows=None):
    """One row per charge_id. Distinct ids are never dropped and never added together.

    landing/silver can repeat a charge_id. The previous notebook kept a single
    legacy row via row_number() partitioned by charge_id. When the copies differ,
    keep the copy that matches the charge already stored in silver (amount first),
    then the earliest landing row.
    """
    live_by_id = {}
    for row in live_rows or []:
        cid = row.get("charge_id")
        if cid and cid not in live_by_id:
            live_by_id[cid] = row
    groups = {}
    order = []
    no_id = []
    for row in rows:
        cid = row.get("charge_id")
        if not cid:
            no_id.append(row)
            continue
        if cid not in groups:
            order.append(cid)
            groups[cid] = []
        groups[cid].append(row)
    chosen = []
    for cid in order:
        group = groups[cid]
        if len(group) == 1:
            chosen.append(group[0])
            continue
        live = live_by_id.get(cid)
        best_i = 0
        best_key = None
        for i, row in enumerate(group):
            key = (_live_match_score(row, live), -i)
            if best_key is None or key > best_key:
                best_key = key
                best_i = i
        chosen.append(group[best_i])
    return chosen + no_id

def reconcile_charges(legacy_rows, parsed_rows, live_rows=None):
    """Union legacy silver with a fresh bronze parse, one row per charge.

    Legacy wins on charge_id collision. Repeated legacy charge_ids collapse to
    one survivor (the live silver value when the copies differ). A row whose
    normalized merchant was the broad NAVARRA collapse is updated from the raw
    merchant / reparse and keeps its existing charge_id, so the next rebuild
    cannot insert a second row. Different charge_ids are all retained.
    """
    legacy = _collapse_duplicate_charge_ids(
        [correct_stored_merchant(r) for r in legacy_rows], live_rows)
    parsed = _dedupe_parsed(parsed_rows)
    used = set()

    def open_indexes():
        return [i for i in range(len(legacy)) if i not in used]

    for p in parsed:
        mid = (p.get("message_id") or "").strip()
        if not mid:
            continue
        hits = [i for i in open_indexes() if (legacy[i].get("message_id") or "").strip() == mid]
        if len(hits) == 1:
            used.add(hits[0])
            legacy[hits[0]] = _merge_pair(legacy[hits[0]], p)
            p["_consumed"] = True

    by_key = {}
    for p in parsed:
        if p.get("_consumed"):
            continue
        by_key.setdefault(_natural_key(p), []).append(p)
    leg_by_key = {}
    for i in open_indexes():
        leg_by_key.setdefault(_natural_key(legacy[i]), []).append(i)

    for key, group in by_key.items():
        cands = [i for i in leg_by_key.get(key, []) if i not in used]
        if len(group) != 1 or len(cands) != 1:
            continue
        p = group[0]
        i = cands[0]
        if not _can_attach(legacy[i], p):
            continue
        used.add(i)
        legacy[i] = _merge_pair(legacy[i], p)
        p["_consumed"] = True

    result = list(legacy)
    seen_ids = {r.get("charge_id") for r in result}
    legacy_ids = set(seen_ids)
    for p in parsed:
        if p.get("_consumed"):
            continue
        cid = p.get("charge_id")
        if cid in seen_ids:
            continue  # legacy wins
        key = _natural_key(p)
        # A reparse whose normalized name changed must not be inserted beside the
        # legacy row it failed to attach to. Two new charges (no legacy row) keep
        # both ids: coffee and the workshop can share a date and an amount.
        if _navarra_related(p) and any(
            _natural_key(r) == key and _navarra_related(r) and r.get("charge_id") in legacy_ids
            for r in result
        ):
            continue
        seen_ids.add(cid)
        result.append(p)
    for row in result:
        row.pop("_consumed", None)
    return result
# --- end alert_parser ---

print(f"parser ready; SEED patterns={len(SEED)}")

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.window import Window
now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
map_df = spark.createDataFrame([(p, c, "money_coach_seed", now_ts) for p, c in SEED],
    schema="merchant_pattern string, category string, source string, updated_at string").withColumn("updated_at", F.to_timestamp("updated_at"))
if not DRY_RUN:
    map_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(MAP_TABLE)
print(f"map rows={map_df.count()}")

# COMMAND ----------

# Bronze: all landing/gmail/*.jsonl, dedupe by message_id
bronze_raw = (spark.read.json(BRONZE_PATH + "*.jsonl")
    .withColumn("_file", F.col("_metadata.file_name"))
    .select(
        F.col("message_id").cast("string"), F.col("thread_id").cast("string"), F.col("bank").cast("string"),
        F.col("sender").cast("string"), F.col("subject").cast("string"),
        F.to_timestamp(F.col("received_at")).alias("received_at"),
        F.col("snippet").cast("string"), F.col("body_text").cast("string"),
        F.coalesce(F.to_timestamp(F.col("ingested_at")), F.current_timestamp()).alias("ingested_at"),
        F.col("_file"))
    .filter(F.col("message_id").isNotNull() & (F.col("message_id") != "")))
w = Window.partitionBy("message_id").orderBy(F.col("ingested_at").desc_nulls_last(), F.col("_file").desc())
bronze_df = bronze_raw.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn", "_file")
n_bronze = bronze_df.count()
print(f"bronze unique message_id={n_bronze}")
if not DRY_RUN:
    bronze_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(BRONZE_TABLE)

# COMMAND ----------

# Silver: legacy history + bronze parsed in this notebook.
# reconcile_charges keeps the historical charge_id when it corrects a NAVARRA collapse.
legacy = spark.read.json(SILVER_PATH).select(
    F.col("charge_id").cast("string"), F.col("message_id").cast("string"),
    F.to_date("charge_date_sv").alias("charge_date_sv"), F.col("amount_usd").cast("double"),
    F.col("merchant").cast("string"), F.col("merchant_norm").cast("string"), F.col("bank").cast("string"),
    F.col("card_last4").cast("string"), F.col("category").cast("string"), F.col("movement_type").cast("string"),
    F.col("is_consumption").cast("boolean"), F.coalesce(F.col("currency").cast("string"), F.lit("USD")).alias("currency"),
    F.col("raw_subject").cast("string"),
    F.coalesce(F.to_timestamp("ingested_at"), F.current_timestamp()).alias("ingested_at"),
).filter(F.col("charge_id").isNotNull())

def _silver_record(row):
    date = row.get("charge_date_sv")
    if hasattr(date, "isoformat"):
        date = date.isoformat()[:10]
    elif date is not None:
        date = str(date)[:10]
    ing = row.get("ingested_at")
    if hasattr(ing, "strftime"):
        ing = ing.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif ing is not None:
        ing = str(ing)
    amt = row.get("amount_usd")
    flag = row.get("is_consumption")
    if isinstance(flag, str):
        flag = flag.strip().lower() in ("1", "true", "yes")
    elif flag is None:
        flag = False
    else:
        flag = bool(flag)
    return {
        "charge_id": row.get("charge_id"),
        "message_id": row.get("message_id"),
        "charge_date_sv": date,
        "amount_usd": None if amt is None else float(amt),
        "merchant": row.get("merchant"),
        "merchant_norm": row.get("merchant_norm"),
        "bank": row.get("bank"),
        "card_last4": row.get("card_last4"),
        "category": row.get("category"),
        "movement_type": row.get("movement_type"),
        "is_consumption": flag,
        "currency": row.get("currency") or "USD",
        "raw_subject": row.get("raw_subject"),
        "ingested_at": ing,
    }

cand = (bronze_df.filter(F.to_date(F.from_utc_timestamp("received_at", "America/El_Salvador")) >= F.lit(PARSE_FROM_SV))
        .select("message_id", "bank", "subject", "snippet", "body_text",
                F.date_format("received_at", "yyyy-MM-dd'T'HH:mm:ss'Z'").alias("received_at")).collect())
parsed_rows, skipped = [], 0
for r in cand:
    s = parse_alert(r.asDict())
    if s is None:
        skipped += 1
        continue
    s["ingested_at"] = now_ts
    parsed_rows.append(s)
legacy_rows = [_silver_record(r.asDict()) for r in legacy.collect()]
from collections import Counter
dup_ids = [cid for cid, n in Counter(r.get("charge_id") for r in legacy_rows).items() if cid and n > 1]
live_rows = []
if dup_ids:
    print(f"landing duplicate charge_ids={len(dup_ids)} (collapse to the live silver value when it differs)")
    try:
        live_df = (spark.table(SILVER_TABLE)
            .where(F.col("charge_id").isin(dup_ids))
            .select("charge_id", "amount_usd", "merchant", "category"))
        live_rows = [_silver_record(r.asDict()) for r in live_df.collect()]
    except Exception as exc:
        print(f"live silver tie-break unavailable ({type(exc).__name__}); earliest landing row wins")
merged = [_silver_record(r) for r in reconcile_charges(legacy_rows, parsed_rows, live_rows)]
_ids = [r.get("charge_id") for r in merged]
if len(_ids) != len(set(_ids)):
    raise Exception(f"duplicate charge_id before silver write: {len(_ids) - len(set(_ids))} extra rows")
legacy_by_id = {}
for r in legacy_rows:
    legacy_by_id.setdefault(r["charge_id"], r)
n_corrected = sum(
    1 for r in merged
    if r["charge_id"] in legacy_by_id and (
        legacy_by_id[r["charge_id"]].get("merchant_norm") != r.get("merchant_norm")
        or legacy_by_id[r["charge_id"]].get("category") != r.get("category")
        or legacy_by_id[r["charge_id"]].get("merchant") != r.get("merchant")
    )
)
print(f"bronze candidates={len(cand)} parsed_charges={len(parsed_rows)} non_charge_emails={skipped} navarra_family_corrections={n_corrected}")
silver_schema = "charge_id string, message_id string, charge_date_sv string, amount_usd double, merchant string, merchant_norm string, bank string, card_last4 string, category string, movement_type string, is_consumption boolean, currency string, raw_subject string, ingested_at string"
silver_df = spark.createDataFrame(merged or [], schema=silver_schema) \
    .withColumn("charge_date_sv", F.to_date("charge_date_sv")).withColumn("ingested_at", F.to_timestamp("ingested_at"))
n_silver = silver_df.count()
print(f"silver rows={n_silver} (legacy={len(legacy_rows)}, parsed={len(parsed_rows)}, corrections={n_corrected})")
if not DRY_RUN:
    silver_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(SILVER_TABLE)

# COMMAND ----------

# Verify + freshness
src = spark.table(SILVER_TABLE) if not DRY_RUN else silver_df
v = src.agg(F.count("*").alias("n_all"), F.countDistinct("charge_id").alias("n_ids"),
            F.max("charge_date_sv").alias("max_charge_date_sv"),
            F.round(F.sum(F.when(F.col("is_consumption"), F.col("amount_usd")).otherwise(0)), 2).alias("usd_cons")).collect()[0]
print("VERIFY", v.asDict())
assert v["n_all"] == v["n_ids"], "duplicate charge_id in silver"
max_recv = bronze_df.agg(F.max("received_at")).collect()[0][0]
now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
bronze_age_days = (now_utc - max_recv).total_seconds() / 86400 if max_recv else 999
today_sv = (datetime.now(timezone.utc) - timedelta(hours=6)).date()
charge_age_days = (today_sv - v["max_charge_date_sv"]).days if v["max_charge_date_sv"] else 999
print(f"freshness: newest bronze received_at={max_recv} UTC ({bronze_age_days:.2f} d old); max charge_date_sv={v['max_charge_date_sv']} ({charge_age_days} d old)")
if charge_age_days > WARN_CHARGE_DAYS:
    print(f"WARNING: newest charge is {charge_age_days} days old (> {WARN_CHARGE_DAYS}); may be a quiet period")
if bronze_age_days > FAIL_BRONZE_DAYS:
    raise Exception(f"FRESHNESS FAIL: no new alert email in {bronze_age_days:.1f} days (> {FAIL_BRONZE_DAYS}). Gmail ingest is not landing files.")
print("DONE")
