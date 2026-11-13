#!/usr/bin/env python3
"""Daily Gmail -> Volume ingest for personal_expenses.

Input: JSON file with a list of Gmail messages fetched (read-only) from the allowlisted bank senders:
  [{"id","thread_id" (or "threadId"),"from","subject","date","body","snippet"?}, ...]
Writes raw bronze rows (NO parsing into silver here; the ETL notebook parses) to
  /Volumes/workspace/personal_expenses/landing/gmail/inc_YYYYMMDD_HHMM.jsonl via the Files API.
Prints a local silver preview using the same parser the notebook uses.

Usage: DATABRICKS_TOKEN=... python3 daily_gmail_ingest.py messages.json [--dry-run]
"""
import json, os, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from alert_parser import bank_for_sender, parse_alert
from masking import mask_card, mask_pii_text

HOST = os.environ.get("DATABRICKS_HOST", "https://dbc-6b5953ee-73b5.cloud.databricks.com").rstrip("/")
VOL_DIR = "/Volumes/workspace/personal_expenses/landing/gmail"
LOCAL = Path(os.environ.get("LOCAL_LANDING_DIR") or (Path(__file__).resolve().parent.parent / "landing"))
LOCAL.mkdir(parents=True, exist_ok=True)

def to_bronze(msgs, fname, now):
    rows, seen = [], set()
    for m in msgs:
        mid = m.get("id") or m.get("message_id")
        sender, bank = bank_for_sender(m.get("from"))
        if not mid or not bank or mid in seen:
            continue  # not allowlisted -> dropped
        seen.add(mid)
        rows.append({
            "message_id": mid,
            "thread_id": m.get("thread_id") or m.get("threadId") or "",
            "bank": bank, "sender": sender,
            "subject": (m.get("subject") or "").strip(),
            "received_at": m.get("date"),
            "snippet": m.get("snippet") or "",
            "body_text": (m.get("body") or "")[:8000],
            "source_file": fname,
            "ingested_at": now,
        })
    return rows

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    msgs = json.load(open(args[0]))
    stamp = datetime.now().strftime("%Y%m%d_%H%M")  # box clock = America/El_Salvador
    fname = f"inc_{stamp}.jsonl"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = to_bronze(msgs, fname, now)
    silver = {}
    for r in rows:
        s = parse_alert(r)
        if s: silver[s["charge_id"]] = s
    print(f"input={len(msgs)} bronze_rows={len(rows)} silver_preview={len(silver)}")
    mask_output = "--masked" in sys.argv or "--live-demo" in sys.argv or os.environ.get("DEMO_MASK_PII") == "1"
    for s in sorted(silver.values(), key=lambda x: x["charge_date_sv"]):
        card = mask_card(s['card_last4']) if mask_output else s['card_last4']
        merch = mask_pii_text(s['merchant']) if mask_output else s['merchant']
        print(f"  {s['charge_date_sv']} {s['bank']:<10} {card:<4} {s['amount_usd']:>9.2f} {s['movement_type']:<12} {s['category']:<13} {merch}")
    if not rows:
        print("nothing to upload"); return
    local = LOCAL / fname
    local.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    if dry:
        print("dry-run: wrote", local); return
    req = urllib.request.Request(f"{HOST}/api/2.0/fs/files{VOL_DIR}/{fname}?overwrite=true", data=local.read_bytes(), method="PUT",
        headers={"Authorization": f"Bearer {os.environ['DATABRICKS_TOKEN']}", "Content-Type": "application/octet-stream"})
    urllib.request.urlopen(req, timeout=120).read()
    print("uploaded", f"{VOL_DIR}/{fname}")

if __name__ == "__main__":
    main()
