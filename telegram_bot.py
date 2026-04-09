#!/usr/bin/env python3
"""
Career-Ops Telegram Bot
Listens for commands and triggers job scanner or manual application generation.

Commands:
    /run        — Trigger full job scan (same as daily cron)
    /status     — Show last scan stats
    /help       — Show available commands

Setup:
    TELEGRAM_BOT_TOKEN   — From BotFather
    TELEGRAM_CHAT_ID     — Your personal chat ID (get from /start)
"""

import os
import sys
import logging
import subprocess
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_2", "")
ALLOWED_CHAT_IDS = set(filter(None, [
    os.getenv("TELEGRAM_CHAT_ID", ""),
    os.getenv("TELEGRAM_CHAT_ID_2", ""),
]))
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = Path(os.getenv("JOB_SCANNER_OUTPUT_DIR", SCRIPT_DIR / "output"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


# ─── TELEGRAM HELPERS ────────────────────────────────────────────────────────

def send_message(chat_id: str, text: str, parse_mode: str = "HTML") -> dict:
    resp = requests.post(
        f"{BASE_URL}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        },
        timeout=35,
    )
    return resp.json()


def get_updates(offset: int = 0) -> list:
    resp = requests.get(
        f"{BASE_URL}/getUpdates",
        params={
            "offset": offset,
            "timeout": 30,
            "allowed_updates": ["message"],
        },
        timeout=35,
    )
    return resp.json().get("result", [])


# ─── COMMAND HANDLERS ────────────────────────────────────────────────────────

def handle_run(chat_id: str):
    """Trigger full job scan."""
    send_message(
        chat_id,
        "🚀 <b>Career-Ops scan starting...</b>\n"
        "This takes 5–10 minutes. I'll message you when done.",
    )
    log.info("Triggering job_scanner.py")

    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "job_scanner.py")],
            capture_output=True,
            text=True,
            timeout=900,  # 15 min max
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            summary_lines = [
                l for l in lines
                if any(k in l for k in ["Sources", "fetched", "Scored", "Pipeline", "Partial"])
            ]
            summary = "\n".join(summary_lines[-8:]) if summary_lines else "Scan complete."
            send_message(
                chat_id,
                "✅ <b>Scan complete!</b>\n\n"
                f"<pre>{summary}</pre>\n\n"
                "Check your email for the briefing + CV attachments.",
            )
        else:
            err = result.stderr[-500:] if result.stderr else "Unknown error"
            send_message(chat_id, f"❌ <b>Scan failed</b>\n<pre>{err}</pre>")

    except subprocess.TimeoutExpired:
        send_message(chat_id, "⏰ Scan timed out after 15 minutes. Check Railway logs.")
    except Exception as exc:
        send_message(chat_id, f"❌ Error: {exc}")


def handle_status(chat_id: str):
    """Show last scan stats from most recent log."""
    log_file = OUTPUT_DIR / "scanner.log"
    if not log_file.exists():
        send_message(chat_id, "No scan logs found yet. Run /run to start a scan.")
        return

    with open(log_file, "r") as f:
        lines = f.readlines()
    last_lines = "".join(lines[-20:])
    send_message(chat_id, f"📋 <b>Last scan log:</b>\n<pre>{last_lines[-800:]}</pre>")


def handle_help(chat_id: str):
    send_message(
        chat_id,
        """🤖 <b>Career-Ops Bot</b>

/run — Trigger full job scan now
    Scans all sources, scores with Claude, generates CVs + cover letters, sends email briefing

/status — Show last scan log

/help — This message

<i>Daily scan runs automatically at 10:00 CET</i>""",
    )


def handle_unknown(chat_id: str, text: str):
    send_message(
        chat_id,
        f"Unknown command: <code>{text}</code>\n\nUse /help to see available commands.",
    )


# ─── MAIN LOOP ───────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    log.info("Career-Ops Telegram bot started")

    # Send startup message to allowed chats (if configured)
    for chat_id in sorted(ALLOWED_CHAT_IDS):
        send_message(
            chat_id,
            "🤖 <b>Career-Ops bot online</b>\n\nUse /run to trigger a scan or /help for commands.",
        )

    offset = 0
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text", "") or "").strip()

                if not chat_id or not text:
                    continue

                # Security: only respond to allow-listed chats (if configured)
                if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
                    log.warning(f"Ignored message from unknown chat_id: {chat_id}")
                    continue

                log.info(f"Command received: {text}")

                if text.startswith("/run"):
                    handle_run(chat_id)
                elif text.startswith("/status"):
                    handle_status(chat_id)
                elif text.startswith("/help") or text == "/start":
                    handle_help(chat_id)
                else:
                    handle_unknown(chat_id, text)

        except Exception as exc:
            log.error(f"Bot loop error: {exc}")


if __name__ == "__main__":
    main()

