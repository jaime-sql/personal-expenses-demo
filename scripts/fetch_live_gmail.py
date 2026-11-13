#!/usr/bin/env python3
"""Fetch recent bank alerts from Gmail using the gmail CLI tool."""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

QUERY = "from:(soluciones@promericaotp.com.sv OR alertas_tarjeta@credicomer.com.sv OR notificaciones_clientes@credicomer.com.sv OR noreply@bi.com.sv OR notificaciones@bancocuscatlan.com OR info@baccredomatic.com) newer_than:7d"

def run_cmd(args):
    cmd = ["gmail.cmd"] + args if os.name == "nt" else ["gmail"] + args
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        raise RuntimeError(f"Command failed ({res.returncode}): {res.stderr}")
    return res.stdout

def decode_b64(data_str):
    if not data_str:
        return ""
    padded = data_str.replace("-", "+").replace("_", "/")
    padded += "=" * ((4 - len(padded) % 4) % 4)
    try:
        return base64.b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return ""

def extract_body(payload):
    parts = [payload]
    body_text = ""
    while parts:
        curr = parts.pop(0)
        mime = curr.get("mimeType", "")
        bdata = curr.get("body", {}).get("data", "")
        if bdata:
            decoded = decode_b64(bdata)
            if "text/plain" in mime:
                return decoded
            elif "text/html" in mime and not body_text:
                body_text = decoded
        subparts = curr.get("parts", [])
        if subparts:
            parts.extend(subparts)
    return body_text

def get_header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""

def main():
    max_count = sys.argv[1] if len(sys.argv) > 1 else "25"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "landing/messages.json"
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)

    print(f"Searching Gmail with query: {QUERY} (limit {max_count})...")
    raw_search = run_cmd(["readonly", "search", QUERY, "--max", max_count, "--json"])
    search_results = json.loads(raw_search) if raw_search.strip() else []
    print(f"Found {len(search_results)} matching message IDs.")

    messages = []
    for i, item in enumerate(search_results, 1):
        mid = item.get("id")
        tid = item.get("threadId") or mid
        print(f"[{i}/{len(search_results)}] Fetching message {mid}...")
        raw_msg = run_cmd(["readonly", "get", mid, "--json"])
        data = json.loads(raw_msg)
        payload = data.get("payload", {})
        headers = payload.get("headers", [])

        sender = get_header(headers, "From")
        subject = get_header(headers, "Subject")
        date_str = get_header(headers, "Date")
        snippet = data.get("snippet", "")
        body = extract_body(payload)

        messages.append({
            "id": mid,
            "thread_id": tid,
            "from": sender,
            "subject": subject,
            "date": date_str,
            "snippet": snippet,
            "body": body,
        })

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(messages)} messages to {out_file}")

if __name__ == "__main__":
    main()
