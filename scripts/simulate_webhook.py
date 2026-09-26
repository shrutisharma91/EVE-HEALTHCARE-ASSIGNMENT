"""Send a signed payment webhook, including duplicates, to a running server.

Example:
    python scripts/simulate_webhook.py --provider-reference sim_pay_abc --times 3
"""

import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Send a signed webhook N times.")
    parser.add_argument("--url", default="http://localhost:8000/payments/webhook/")
    parser.add_argument("--event-id", default="evt_demo")
    parser.add_argument("--event-type", default="payment.succeeded")
    parser.add_argument("--provider-reference", default="sim_pay_demo")
    parser.add_argument("--amount", default="499.00")
    parser.add_argument("--currency", default="INR")
    parser.add_argument("--times", type=int, default=3)
    parser.add_argument("--secret", default=os.environ.get("WEBHOOK_SECRET", ""))
    args = parser.parse_args()
    if not args.secret:
        raise SystemExit("Set WEBHOOK_SECRET or pass --secret.")

    payload = {
        "event_id": args.event_id,
        "event_type": args.event_type,
        "data": {
            "provider_reference": args.provider_reference,
            "amount": args.amount,
            "currency": args.currency,
        },
        "created_at": "2026-09-26T10:00:00Z",
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()
    timestamp = str(int(time.time()))

    for attempt in range(1, args.times + 1):
        request = urllib.request.Request(
            args.url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": f"sha256={signature}",
                "X-Webhook-Timestamp": timestamp,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                text = response.read().decode()
                print(f"POST {attempt} -> {response.status} {text}")
        except urllib.error.HTTPError as exc:
            text = exc.read().decode()
            print(f"POST {attempt} -> {exc.code} {text}")


if __name__ == "__main__":
    main()
