import os
import sqlite3
import logging
import time
import traceback
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "rep.db")
START_TIME = time.time()

# Users who have sent /add and are waiting to send a file or link
PENDING_ADD: set[int] = set()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_name TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ðŸ‘‹ Welcome to *Rep* â€” the shared file vault!\n\n"
        "â€¢ *Videos* are saved automatically whenever you send one.\n"
        "â€¢ *Documents and links* require */add* first, then send the file or URL.\n\n"
        "Commands:\n"
        "â€¢ /add â€” arm the bot to save your next document or link\n"
        "â€¢ /list â€” see how many files and links are saved\n"
        "â€¢ /send â€” get everything (files + links)\n"
        "â€¢ /files â€” get only saved files\n"
        "â€¢ /links â€” get only saved links\n\n"
        "To *search*, just type any keyword and I'll find matching files and links.",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Rep Bot â€” Command Reference*\n\n"
        "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
        "*Saving videos*\n"
        "Send any *video* â€” it is saved automatically, no command needed.\n\n"
        "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
        "*Saving documents and links (explicit /add required)*\n"
        "1. Send */add*\n"
        "2. Immediately send a *file/document* or *link* (http/https)\n"
        "The item is saved to the shared vault.\n"
        "_Without /add, documents and links are ignored._\n\n"
        "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
        "*/add*\n"
        "Arms the bot to save your next document or link. One item per /add.\n"
        "_Example: /add â†’ then send a file or URL_\n\n"
        "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
        "*/list*\n"
        "Shows a summary of everything in the shared vault.\n\n"
        "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
        "*/send*\n"
        "Sends all shared files and links back to you.\n\n"
        "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
        "*/files*\n"
        "Sends only the shared files (videos and documents).\n\n"
        "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
        "*/links*\n"
        "Sends only the shared links.\n\n"
        "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
        "*Search (keyword)*\n"
        "Type any word or phrase (not a command, not a URL) to search the vault.\n"
        "Finds files by name and links by URL â€” partial, case-insensitive.\n"
        "_Example: report â†’ finds \"report.pdf\", \"https://site.com/report\"_\n\n"
        "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”\n\n"
        "*/ping* â€” Check the bot is alive and see its uptime\n"
        "*/start* â€” Show the welcome message\n"
        "*/help* or */commands* â€” Show this reference",
        parse_mode="Markdown",
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    elapsed = int(time.time() - START_TIME)
    days, rem = divmod(elapsed, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")

    uptime_str = " ".join(parts)
    await update.message.reply_text(f"Pong! Bot is alive.\nUptime: {uptime_str}")


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    PENDING_ADD.add(user_id)
    await update.message.reply_text(
        "Ready to save. Send your file or link now."
    )


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    video = update.message.video or update.message.video_note
    file_id = video.file_id

    with get_db() as conn:
        conn.execute(
            "INSERT INTO files (user_id, file_id, file_type) VALUES (?, ?, ?)",
            (user_id, file_id, "video"),
        )
        conn.commit()

    await update.message.reply_text("Video saved to the shared vault!")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in PENDING_ADD:
        return

    PENDING_ADD.discard(user_id)
    doc = update.message.document
    file_id = doc.file_id
    file_name = doc.file_name or "file"

    with get_db() as conn:
        conn.execute(
            "INSERT INTO files (user_id, file_id, file_type, file_name) VALUES (?, ?, ?, ?)",
            (user_id, file_id, "document", file_name),
        )
        conn.commit()

    await update.message.reply_text(f"File *{file_name}* saved to the shared vault!", parse_mode="Markdown")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    if text.startswith("http://") or text.startswith("https://"):
        if user_id not in PENDING_ADD:
            return

        PENDING_ADD.discard(user_id)
        with get_db() as conn:
            conn.execute(
                "INSERT INTO links (user_id, url) VALUES (?, ?)",
                (user_id, text),
            )
            conn.commit()
        await update.message.reply_text("Link saved to the shared vault!")
        return

    keyword = text.lower()
    with get_db() as conn:
        matched_files = conn.execute(
            "SELECT file_id, file_type, file_name FROM files "
            "WHERE LOWER(COALESCE(file_name, '')) LIKE ?",
            (f"%{keyword}%",),
        ).fetchall()
        matched_links = conn.execute(
            "SELECT url FROM links WHERE LOWER(url) LIKE ?",
            (f"%{keyword}%",),
        ).fetchall()

    total = len(matched_files) + len(matched_links)

    if total == 0:
        await update.message.reply_text(
            f'No results found for "*{text}*".',
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        f'Found *{total}* result{"s" if total != 1 else ""} for "*{text}*":',
        parse_mode="Markdown",
    )

    for row in matched_files:
        try:
            if row["file_type"] == "video":
                await update.message.reply_video(video=row["file_id"])
            else:
                await update.message.reply_document(document=row["file_id"])
        except Exception as e:
            logger.error(f"Failed to send file {row['file_id']}: {e}")
            name = row["file_name"] or "a file"
            await update.message.reply_text(
                f"Could not resend {name} (it may have expired on Telegram's servers)."
            )

    for row in matched_links:
        await update.message.reply_text(row["url"])


async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        file_rows = conn.execute(
            "SELECT file_type, COUNT(*) as cnt FROM files GROUP BY file_type"
        ).fetchall()
        link_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM links"
        ).fetchone()["cnt"]

    if not file_rows and link_count == 0:
        await update.message.reply_text(
            "The shared vault is empty. Use /add then send a file or link to get started!"
        )
        return

    lines = []
    total = 0

    for row in file_rows:
        count = row["cnt"]
        total += count
        label = "video" if row["file_type"] == "video" else "document"
        lines.append(f"â€¢ {count} {label}{'s' if count != 1 else ''}")

    if link_count > 0:
        total += link_count
        lines.append(f"â€¢ {link_count} link{'s' if link_count != 1 else ''}")

    await update.message.reply_text(
        f"The shared vault has *{total}* item{'s' if total != 1 else ''}:\n" + "\n".join(lines),
        parse_mode="Markdown",
    )


async def send_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        file_rows = conn.execute(
            "SELECT file_id, file_type, file_name FROM files ORDER BY added_at"
        ).fetchall()
        link_rows = conn.execute(
            "SELECT url FROM links ORDER BY added_at"
        ).fetchall()

    total = len(file_rows) + len(link_rows)

    if total == 0:
        await update.message.reply_text(
            "The shared vault is empty. Use /add then send a file or link to get started!"
        )
        return

    await update.message.reply_text(f"Sending {total} shared item{'s' if total != 1 else ''}...")

    for row in file_rows:
        try:
            if row["file_type"] == "video":
                await update.message.reply_video(video=row["file_id"])
            else:
                await update.message.reply_document(document=row["file_id"])
        except Exception as e:
            logger.error(f"Failed to send file {row['file_id']}: {e}")
            name = row["file_name"] or "a file"
            await update.message.reply_text(
                f"Could not resend {name} (it may have expired on Telegram's servers)."
            )

    for row in link_rows:
        await update.message.reply_text(row["url"])


async def send_only_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        file_rows = conn.execute(
            "SELECT file_id, file_type, file_name FROM files ORDER BY added_at"
        ).fetchall()

    if not file_rows:
        await update.message.reply_text(
            "No files in the shared vault yet. Use /add then send a file to get started!"
        )
        return

    await update.message.reply_text(
        f"Sending {len(file_rows)} shared file{'s' if len(file_rows) != 1 else ''}..."
    )

    for row in file_rows:
        try:
            if row["file_type"] == "video":
                await update.message.reply_video(video=row["file_id"])
            else:
                await update.message.reply_document(document=row["file_id"])
        except Exception as e:
            logger.error(f"Failed to send file {row['file_id']}: {e}")
            name = row["file_name"] or "a file"
            await update.message.reply_text(
                f"Could not resend {name} (it may have expired on Telegram's servers)."
            )


async def send_only_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        link_rows = conn.execute(
            "SELECT url FROM links ORDER BY added_at"
        ).fetchall()

    if not link_rows:
        await update.message.reply_text(
            "No links in the shared vault yet. Use /add then send a URL to get started!"
        )
        return

    count = len(link_rows)
    await update.message.reply_text(f"Sending {count} shared link{'s' if count != 1 else ''}...")
    for row in link_rows:
        await update.message.reply_text(row["url"])


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    init_db()

    app = (
        ApplicationBuilder()
        .token(token)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("commands", help_command))
    app.add_handler(CommandHandler("list", list_files))
    app.add_handler(CommandHandler("send", send_files))
    app.add_handler(CommandHandler("files", send_only_files))
    app.add_handler(CommandHandler("links", send_only_links))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, handle_video))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Unhandled exception in handler:", exc_info=context.error)

    app.add_error_handler(error_handler)

    logger.info("Rep bot is running...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


def start_health_server(port: int) -> None:
    import json

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            uptime = int(time.time() - START_TIME)
            body = json.dumps({
                "status": "ok",
                "uptime_seconds": uptime,
                "bot": "Rep",
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health server listening on port %d", port)


def start_self_ping(url: str, interval: int = 240) -> None:
    def ping():
        while True:
            time.sleep(interval)
            try:
                urllib.request.urlopen(url, timeout=10)
                logger.info("Self-ping OK â†’ %s", url)
            except Exception as e:
                logger.warning("Self-ping failed: %s", e)

    thread = threading.Thread(target=ping, daemon=True)
    thread.start()
    logger.info("Self-ping active every %ds â†’ %s", interval, url)


if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 3000))
    start_health_server(PORT)

    replit_domains = os.environ.get("REPLIT_DOMAINS", "")
    if replit_domains:
        primary_domain = replit_domains.split(",")[0].strip()
        public_url = f"https://{primary_domain}/"
    else:
        public_url = f"http://localhost:{PORT}/"

    logger.info("Public health URL: %s", public_url)
    logger.info(
        "To keep this bot alive on free tier: add %s to UptimeRobot "
        "(https://uptimerobot.com) with a 5-minute HTTP monitor.",
        public_url,
    )

    start_self_ping(public_url, interval=240)

    RETRY_DELAY = 5
    while True:
        try:
            main()
        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception:
            logger.error("Bot crashed â€” restarting in %ds...\n%s", RETRY_DELAY, traceback.format_exc())
            time.sleep(RETRY_DELAY)
