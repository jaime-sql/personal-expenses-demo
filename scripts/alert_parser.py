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
