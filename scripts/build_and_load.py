#!/usr/bin/env python3
"""Build personal_expenses bronze/silver from Money Coach YTD + seed map; upload landing; load Databricks."""
import csv, json, re, os, time, uuid
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import urllib.request
from alert_parser import SEED, norm_merchant, classify, charge_id

HOST = os.environ.get("DATABRICKS_HOST", "https://dbc-6b5953ee-73b5.cloud.databricks.com").rstrip("/")
TOKEN = os.environ["DATABRICKS_TOKEN"]
WH = "de62669408c45fc9"
OUT = Path("/workspace/personal_expenses/out")
LANDING = Path("/workspace/personal_expenses/landing")
OUT.mkdir(parents=True, exist_ok=True)
LANDING.mkdir(parents=True, exist_ok=True)

# Merchant normalization and categories come from alert_parser (same rules as the daily ETL).

XFER_MARKERS = [
    "TRANSFER365", "TOROGOZ", "PAGO TARJETA", "PAGO DE TARJETA", "ABONO A TARJETA",
    "PAGO TC", "PAYMENT THANK", "BANCA DIGITAL", "ABONO A TARJETA", "TRANSACCION PENDIENTE",
]
CARD_PAY_MARKERS = ["PAGO TARJETA", "PAGO DE TARJETA", "ABONO A TARJETA", "PAGO TC", "PAYMENT THANK YOU", "PAYMENT THANK"]

ALLOWLIST = {
    "soluciones@promericaotp.com.sv": "Promerica",
    "alertas_tarjeta@credicomer.com.sv": "Credicomer",
    "notificaciones_clientes@credicomer.com.sv": "Credicomer",
    "noreply@bi.com.sv": "BI",
    "notificaciones@bancocuscatlan.com": "Cuscatlán",
    "info@baccredomatic.com": "BAC",
}

def api(method, path, body=None, raw=False):
    data = None if body is None else (body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode())
    req = urllib.request.Request(
        HOST + path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", **({"Content-Type": "application/json"} if body is not None and not isinstance(body, (bytes, bytearray)) else {})},
    )
    if isinstance(body, (bytes, bytearray)):
        req.add_header("Content-Type", "application/octet-stream")
    with urllib.request.urlopen(req, timeout=120) as r:
        raw_b = r.read()
        if raw:
            return raw_b
        if not raw_b:
            return {}
        return json.loads(raw_b.decode())

def sql(statement, wait="50s"):
    payload = {
        "warehouse_id": WH,
        "catalog": "workspace",
        "schema": "personal_expenses",
        "statement": statement,
        "wait_timeout": wait,
    }
    res = api("POST", "/api/2.0/sql/statements", payload)
    sid = res.get("statement_id")
    state = res.get("status", {}).get("state")
    while state in ("PENDING", "RUNNING"):
        time.sleep(1.5)
        res = api("GET", f"/api/2.0/sql/statements/{sid}")
        state = res.get("status", {}).get("state")
    if state != "SUCCEEDED":
        raise RuntimeError(json.dumps(res)[:1500])
    return res

def esc(s):
    if s is None:
        return "NULL"
    return "'" + str(s).replace("\\", "\\\\").replace("'", "''") + "'"

REFUND_MARKERS = [
    "REEMBOLSO", "REFUND", "CARGO REVERTIDO", "REVERSI", "ANULACI", "DEVOLUCI",
    "CREDIT ADJUSTMENT", "AJUSTE DE CREDITO", "AJUSTE DE CRÉDITO",
]

def movement_type(merchant, category=None, subject=""):
    blob = f"{merchant or ''} {subject or ''} {category or ''}".upper()
    if any(k in blob for k in REFUND_MARKERS):
        return "refund"
    if any(k in blob for k in CARD_PAY_MARKERS):
        return "card_payment"
    if category == "transfers" or any(k in blob for k in ["TRANSFER365", "TOROGOZ", "BANCA DIGITAL", "TRANSFERENCIA"]):
        return "transfer"
    # Utility Pago de Servicio stays purchase/consumption
    return "purchase"

def load_ytd():
    rows = list(csv.DictReader(open("/workspace/ytd_spend/ytd_full.csv")))
    silver = []
    seen = set()
    for r in rows:
        merch = r["merchant"]
        nm = norm_merchant(merch)
        cat = classify(merch, r.get("category"))
        mt = movement_type(merch, cat)
        # Money Coach already tagged transfers category
        if cat == "transfers":
            mt = "transfer"
        cid = charge_id(r["bank"], r.get("card") or "", r["date"], r["amount"], nm)
        if cid in seen:
            continue
        seen.add(cid)
        silver.append({
            "charge_id": cid,
            "message_id": r["id"],
            "charge_date_sv": r["date"],
            "amount_usd": round(float(r["amount"]), 2),
            "merchant": merch,
            "merchant_norm": nm,
            "bank": r["bank"],
            "card_last4": (r.get("card") or "").replace("*", "").strip()[-4:],
            "category": cat,
            "movement_type": mt,
            "is_consumption": mt == "purchase",  # refund/card_payment/transfer are non-consumption
            "currency": "USD",
            "raw_subject": "",
            "ingested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "src": r.get("src") or "ytd_full",
        })
    return silver

def build_landing_from_pages():
    """Harvest allowlisted envelopes from Money Coach page dumps into landing JSONL."""
    pages = list(Path("/workspace/ytd_spend").glob("*.txt"))
    pages += list(Path("/workspace/ytd_spend/pago_bodies").glob("*.txt"))
    pages += list(Path("/workspace/ytd_spend/bi_bodies").glob("*.txt"))
    records = {}
    for p in pages:
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        # extract JSON message objects loosely
        for m in re.finditer(r'\{\s*"id"\s*:\s*"([a-f0-9]+)"\s*,\s*"threadId"\s*:\s*"([a-f0-9]+)"\s*,\s*"from"\s*:\s*"([^"]*)"', text):
            mid, tid, frm = m.group(1), m.group(2), m.group(3)
            frm_l = frm.lower()
            bank = None
            for email, b in ALLOWLIST.items():
                if email in frm_l:
                    bank = b
                    break
            if not bank:
                continue
            # try to find subject/date/snippet nearby
            chunk = text[m.start(): m.start()+1200]
            subj = re.search(r'"subject"\s*:\s*"([^"]*)"', chunk)
            date = re.search(r'"date"\s*:\s*"([^"]*)"', chunk)
            snip = re.search(r'"snippet"\s*:\s*"([^"]*)"', chunk)
            records[mid] = {
                "message_id": mid,
                "thread_id": tid,
                "bank": bank,
                "sender": next(e for e in ALLOWLIST if e in frm_l),
                "subject": subj.group(1) if subj else "",
                "received_at": date.group(1) if date else None,
                "snippet": snip.group(1) if snip else "",
                "body_text": "",
                "source_file": p.name,
            }
        # full read_email dumps (pago/bi bodies)
        if '"body"' in text and text.strip().startswith("{"):
            try:
                # may be redacted wrapper — try find json
                jstart = text.find("{")
                obj = json.loads(text[jstart:])
                mid = obj.get("id")
                frm = (obj.get("from") or "").lower()
                bank = None
                sender = None
                for email, b in ALLOWLIST.items():
                    if email in frm:
                        bank = b; sender = email; break
                if mid and bank:
                    records[mid] = {
                        "message_id": mid,
                        "thread_id": obj.get("threadId"),
                        "bank": bank,
                        "sender": sender,
                        "subject": obj.get("subject") or "",
                        "received_at": obj.get("date"),
                        "snippet": obj.get("snippet") or "",
                        "body_text": (obj.get("body") or "")[:8000],
                        "source_file": p.name,
                    }
            except Exception:
                pass
    return list(records.values())

def main():
    print("1) seed map + silver from ytd_full")
    silver = load_ytd()
    landing = build_landing_from_pages()
    print(f"   silver={len(silver)} landing_msgs={len(landing)}")

    n_all = len(silver)
    s_all = round(sum(r["amount_usd"] for r in silver), 2)
    cons = [r for r in silver if r["is_consumption"]]
    n_cons = len(cons); s_cons = round(sum(r["amount_usd"] for r in cons), 2)
    by_mt = defaultdict(lambda: [0, 0.0])
    for r in silver:
        by_mt[r["movement_type"]][0] += 1
        by_mt[r["movement_type"]][1] += r["amount_usd"]
    stats = {
        "all_movements": {"n": n_all, "usd": s_all},
        "consumption": {"n": n_cons, "usd": s_cons},
        "by_movement_type": {k: {"n": v[0], "usd": round(v[1], 2)} for k, v in by_mt.items()},
        "target_consumption": {"n": 731, "usd": 24819.60},
        "path": "Money Coach ytd_full.csv (Gmail-parsed) → silver; allowlisted envelope dumps → landing/bronze",
        "window": ["2025-10-27", "2026-10-26"],
        "banks": sorted({r["bank"] for r in silver}),
    }
    (OUT / "stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))

    # write silver csv + landing jsonl
    silver_csv = OUT / "silver_charges.csv"
    with silver_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(silver[0].keys()))
        w.writeheader(); w.writerows(silver)

    stamp = datetime.now().strftime("%Y%m%d")
    landing_path = LANDING / f"backfill_{stamp}.jsonl"
    with landing_path.open("w") as f:
        for rec in landing:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # also write silver-derived bronze stubs for message_ids in silver not in landing
    landing_ids = {r["message_id"] for r in landing}
    for r in silver:
        if r["message_id"] not in landing_ids:
            stub = {
                "message_id": r["message_id"],
                "thread_id": "",
                "bank": r["bank"],
                "sender": "",
                "subject": "",
                "received_at": r["charge_date_sv"] + "T12:00:00Z",
                "snippet": f"{r['merchant']} ${r['amount_usd']}",
                "body_text": "",
                "source_file": "ytd_full.csv",
            }
            with landing_path.open("a") as f:
                f.write(json.dumps(stub, ensure_ascii=False) + "\n")
            landing.append(stub)
    print(f"   landing_jsonl={landing_path} rows={len(landing)}")

    # 2) upload landing to volume
    print("2) upload landing to UC Volume")
    vol_path = f"/Volumes/workspace/personal_expenses/landing/gmail/{landing_path.name}"
    data = landing_path.read_bytes()
    # Files API
    try:
        api("PUT", f"/api/2.0/fs/files{vol_path}", data)
        print("   uploaded", vol_path, len(data), "bytes")
    except Exception as e:
        print("   PUT failed", e, "— trying create-upload")
        # fallback: dbfs-like
        raise

    # 3) truncate + load tables via SQL batches
    print("3) load map_merchant_category")
    sql("DELETE FROM workspace.personal_expenses.map_merchant_category")
    values = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for pat, cat in SEED:
        values.append(f"({esc(pat)}, {esc(cat)}, {'Money Coach seed'}, {esc(now)})")
    # also unique norms from silver
    for r in silver:
        values.append(f"({esc(r['merchant_norm'][:60])}, {esc(r['category'])}, {'ytd_derived'}, {esc(now)})")
    # dedupe by inserting in chunks — table has no PK so ok; keep seed distinct
    # recreate cleaner: use seed only + distinct norms
    sql("DELETE FROM workspace.personal_expenses.map_merchant_category WHERE 1=1")
    seed_vals = [f"({esc(p)}, {esc(c)}, {esc('money_coach_seed')}, TIMESTAMP '{now}')" for p, c in SEED]
    for i in range(0, len(seed_vals), 40):
        chunk = ",\n".join(seed_vals[i:i+40])
        sql(f"INSERT INTO workspace.personal_expenses.map_merchant_category (merchant_pattern, category, source, updated_at) VALUES {chunk}")

    print("4) load bronze_mail_alerts")
    sql("DELETE FROM workspace.personal_expenses.bronze_mail_alerts WHERE 1=1")
    # batch insert
    def bronze_row(r):
        ra = r.get("received_at") or None
        ra_sql = f"TIMESTAMP '{ra.replace('Z','')}'" if ra else "NULL"
        return (f"({esc(r['message_id'])}, {esc(r.get('thread_id') or '')}, {esc(r['bank'])}, "
                f"{esc(r.get('sender') or '')}, {esc((r.get('subject') or '')[:300])}, {ra_sql}, "
                f"{esc((r.get('snippet') or '')[:500])}, {esc((r.get('body_text') or '')[:2000])}, "
                f"TIMESTAMP '{now}')")

    for i in range(0, len(landing), 25):
        chunk = landing[i:i+25]
        vals = ",\n".join(bronze_row(r) for r in chunk)
        sql(f"""INSERT INTO workspace.personal_expenses.bronze_mail_alerts
        (message_id, thread_id, bank, sender, subject, received_at, snippet, body_text, ingested_at)
        VALUES {vals}""")
        print(f"   bronze {min(i+25,len(landing))}/{len(landing)}")

    print("5) load silver_charges")
    sql("DELETE FROM workspace.personal_expenses.silver_charges WHERE 1=1")
    def silver_row(r):
        return (f"({esc(r['charge_id'])}, {esc(r['message_id'])}, DATE '{r['charge_date_sv']}', "
                f"{r['amount_usd']}, {esc(r['merchant'][:200])}, {esc(r['merchant_norm'][:120])}, "
                f"{esc(r['bank'])}, {esc(r['card_last4'])}, {esc(r['category'])}, "
                f"{esc(r['movement_type'])}, {str(r['is_consumption']).lower()}, {esc(r['currency'])}, "
                f"{esc(r.get('raw_subject') or '')}, TIMESTAMP '{r['ingested_at'].replace('Z','')}')")

    for i in range(0, len(silver), 30):
        chunk = silver[i:i+30]
        vals = ",\n".join(silver_row(r) for r in chunk)
        sql(f"""INSERT INTO workspace.personal_expenses.silver_charges
        (charge_id, message_id, charge_date_sv, amount_usd, merchant, merchant_norm, bank, card_last4,
         category, movement_type, is_consumption, currency, raw_subject, ingested_at)
        VALUES {vals}""")
        print(f"   silver {min(i+30,len(silver))}/{len(silver)}")

    # verify
    ver = sql("""SELECT
      COUNT(*) n_all,
      ROUND(SUM(amount_usd),2) usd_all,
      SUM(CASE WHEN is_consumption THEN 1 ELSE 0 END) n_cons,
      ROUND(SUM(CASE WHEN is_consumption THEN amount_usd ELSE 0 END),2) usd_cons
    FROM workspace.personal_expenses.silver_charges""")
    print("VERIFY", ver.get("result"))
    (OUT / "verify.json").write_text(json.dumps(ver, indent=2))
    print("DONE")

if __name__ == "__main__":
    main()
