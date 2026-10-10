"""Checks a Myntra product price and sends a Telegram alert when it drops below a threshold.

Runs on GitHub Actions every 20 minutes. Reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from env
(repo secrets). Alerts once per new price below the threshold (no repeat spam); state.json is
committed back to the repo by the workflow.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

URL = "https://www.myntra.com/casual-shoes/new+balance/new-balance-574-grey--men-casual-shoes/26175374/buy"
THRESHOLD = 5000

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"

DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36")

# Myntra sometimes treats cloud IPs differently; try a few browser-like profiles.
HEADER_VARIANTS = [
    {"User-Agent": DESKTOP_UA, "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"},
    {"User-Agent": DESKTOP_UA,
     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
     "Accept-Language": "en-IN,en;q=0.9", "Referer": "https://www.google.com/",
     "Upgrade-Insecure-Requests": "1", "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
     "Sec-Fetch-Site": "cross-site", "Sec-Fetch-User": "?1"},
    {"User-Agent": MOBILE_UA, "Accept": "text/html", "Accept-Language": "en-IN,en;q=0.9"},
]


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}", flush=True)


def get_price():
    for i, headers in enumerate(HEADER_VARIANTS, 1):
        try:
            resp = urllib.request.urlopen(urllib.request.Request(URL, headers=headers), timeout=30)
            status, html = resp.status, resp.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            status, html = e.code, e.read().decode("utf-8", "ignore")
        except Exception as e:
            log(f"variant {i}: request failed: {e!r}")
            continue
        m = re.search(r'"discounted"\s*:\s*(\d+)', html) or re.search(r'"mrp"\s*:\s*(\d+)', html)
        if m:
            return int(m.group(1))
        title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        snippet = re.sub(r"\s+", " ", html[:400])
        log(f"variant {i}: status={status} len={len(html)} "
            f"title={title.group(1).strip()[:100] if title else None!r} start={snippet!r}")
    raise ValueError("price not found in page (layout changed or request blocked)")


def send_telegram(cfg, text):
    data = urllib.parse.urlencode({"chat_id": cfg["chat_id"], "text": text}).encode()
    api = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    urllib.request.urlopen(api, data=data, timeout=30).read()


def main():
    cfg = {"bot_token": os.environ["TELEGRAM_BOT_TOKEN"], "chat_id": os.environ["TELEGRAM_CHAT_ID"]}
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}

    if "--test" in sys.argv or os.environ.get("TEST_MODE") == "true":
        price = get_price()
        send_telegram(cfg, f"Price watcher test OK. New Balance 574 is currently Rs.{price}.")
        log(f"test message sent, price={price}")
        return

    price = get_price()
    log(f"price={price}")

    if price < THRESHOLD:
        if state.get("last_alerted_price") != price:
            send_telegram(cfg, f"Price drop! New Balance 574 Grey is now Rs.{price} "
                               f"(below Rs.{THRESHOLD}).\n{URL}")
            state["last_alerted_price"] = price
            log("alert sent")
    else:
        state.pop("last_alerted_price", None)  # re-arm for the next drop

    STATE.write_text(json.dumps(state), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR: {e!r}")
        sys.exit(1)
