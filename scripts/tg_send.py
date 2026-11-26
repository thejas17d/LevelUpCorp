"""Send a text message and/or files to Thejas's Telegram (bot from .env: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID).

Usage (from the LevelUpCorp folder):
  .venv\\Scripts\\python scripts\\tg_send.py "some text"
  .venv\\Scripts\\python scripts\\tg_send.py --file "C:\\path\\to\\file.pdf" [--file other.xlsx] ["optional caption"]
  echo long text | .venv\\Scripts\\python scripts\\tg_send.py -      (text from stdin)

Long text is split into 4,000-character messages. Files up to 50 MB (Telegram bot limit).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from levelup.config import _load_dotenv  # noqa: E402

_load_dotenv(ROOT / ".env")
TOKEN, CHAT = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
API = f"https://api.telegram.org/bot{TOKEN}"


def send_text(text: str) -> int:
    n = 0
    for i in range(0, len(text), 4000):
        r = requests.post(f"{API}/sendMessage", json={"chat_id": CHAT, "text": text[i:i + 4000],
                                                     "disable_web_page_preview": True}, timeout=30)
        r.raise_for_status(); n += 1
    return n


def send_file(path: str, caption: str = "") -> None:
    p = Path(path)
    with p.open("rb") as fh:
        r = requests.post(f"{API}/sendDocument", data={"chat_id": CHAT, "caption": caption[:1000]},
                          files={"document": (p.name, fh)}, timeout=300)
    r.raise_for_status()


def main() -> None:
    if not (TOKEN and CHAT):
        sys.exit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing in .env")
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default="")
    ap.add_argument("--file", action="append", default=[])
    a = ap.parse_args()
    text = sys.stdin.read() if a.text == "-" else a.text
    for f in a.file:
        send_file(f, caption=text if len(a.file) == 1 else "")
        print("sent file:", f)
    if text and len(a.file) != 1:
        print("sent messages:", send_text(text))


if __name__ == "__main__":
    main()
