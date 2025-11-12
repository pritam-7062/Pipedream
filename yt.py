import os
import tempfile
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from yt_dlp import YoutubeDL
from curl_cffi import requests as curl_requests
from keep_alive import keep_alive

# ========= HARD-CODED CONFIG =========
API_ID = 23352430  # 🔹 Replace with your Telegram API ID
API_HASH = "801e842ff48c36b09d902758e0038a24"
BOT_TOKEN = "7691181086:AAF66rv29AYM0as2KcALEKb82TUDZY3vM9o"

IMPERSONATE_TARGET = "chrome120"
HTTP_TIMEOUT = 10

# ========= LOGGING =========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("yt-bot")

# ========= Pyrogram client =========
app = Client(
    "yt_impersonated_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

# ========= Impersonated session =========
session = curl_requests.Session(impersonate=IMPERSONATE_TARGET, timeout=HTTP_TIMEOUT)

# optional UA mapping for yt_dlp consistency
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " \
             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ========= Helper functions =========
def is_youtube_url(text: str) -> bool:
    return "youtube.com/" in text or "youtu.be/" in text

def build_keyboard(formats, video_id):
    kb = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for f in formats:
        fmt_id = f.get("format_id")
        ext = f.get("ext")
        note = f.get("format_note") or ""
        height = f.get("height")
        abr = f.get("abr")
        size = f.get("filesize") or f.get("filesize_approx")
        label = ""
        if f.get("vcodec") == "none":
            label = f"AUDIO {ext} {int(abr)}kbps" if abr else f"AUDIO {ext}"
        else:
            label = f"{ext} {height}p {note}"
        if size:
            label += f" • {round(size/(1024*1024))}MB"
        buttons.append(InlineKeyboardButton(label, callback_data=f"dl|{video_id}|{fmt_id}"))
    kb.add(*buttons)
    return kb

def fetch_cookies_headers(url: str) -> Dict[str, Any]:
    """Use curl_cffi impersonation to fetch headers and cookies for yt_dlp."""
    logger.info("Fetching headers via impersonation for %s", url)
    r = session.get(url)
    cookies = "; ".join([f"{k}={v}" for k, v in r.cookies.items()])
    headers = dict(r.headers)
    headers["User-Agent"] = USER_AGENT
    return {"cookies": cookies, "headers": headers}

# ========= Command handlers =========
@app.on_message(filters.command(["start", "help"]))
async def start_cmd(client: Client, message: Message):
    await message.reply_text("👋 Send a YouTube link and I'll fetch download options.\n"
                             "⚠️ Use only for legal/personal use.")

@app.on_message(filters.text & ~filters.command(["start", "help"]))
async def handle_link(client: Client, message: Message):
    url = message.text.strip()
    if not is_youtube_url(url):
        return await message.reply_text("❌ Please send a valid YouTube link.")

    status = await message.reply_text("⏳ Fetching video info...")

    try:
        # get cookies + headers via impersonation
        meta = await asyncio.to_thread(fetch_cookies_headers, url)

        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "no_warnings": True,
            "http_headers": meta["headers"],
            "cookiefile": None,  # yt_dlp handles raw cookie headers
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get("formats", [])
        video_id = info.get("id")
        title = info.get("title")

        # filter formats
        audio_formats = [f for f in formats if f.get("vcodec") == "none"]
        video_formats = [f for f in formats if f.get("vcodec") != "none"]
        top_formats = (audio_formats[:3] + sorted(video_formats, key=lambda f: f.get("height", 0), reverse=True)[:5])

        if not top_formats:
            return await status.edit_text("❌ No downloadable formats found.")

        kb = build_keyboard(top_formats, video_id)
        await status.edit_text(f"🎬 *{title}*\nChoose format:", reply_markup=kb)
    except Exception as e:
        logger.exception("Error fetching info")
        await status.edit_text(f"❌ Failed: {e}")

@app.on_callback_query(filters.regex("^dl\\|"))
async def handle_download(client: Client, callback):
    _, video_id, fmt_id = callback.data.split("|")
    chat_id = callback.message.chat.id
    msg = await callback.message.reply_text(f"⬇️ Downloading format `{fmt_id}` ...")

    url = f"https://www.youtube.com/watch?v={video_id}"
    tmpdir = tempfile.mkdtemp(prefix="yt_", dir="tmp")

    try:
        meta = await asyncio.to_thread(fetch_cookies_headers, url)
        outtmpl = os.path.join(tmpdir, "%(title).100s.%(ext)s")

        ydl_opts = {
            "format": fmt_id,
            "outtmpl": outtmpl,
            "quiet": True,
            "noplaylist": True,
            "retries": 3,
            "http_headers": meta["headers"],
            "postprocessors": [{"key": "FFmpegMetadata"}],
        }

        await msg.edit_text("📥 Downloading with impersonated headers...")
        info = await asyncio.to_thread(lambda: YoutubeDL(ydl_opts).download([url]))

        # find file
        files = list(Path(tmpdir).glob("*"))
        if not files:
            return await msg.edit_text("❌ Download finished but no file found.")
        file_path = files[0]
        await msg.edit_text("📤 Uploading to Telegram...")

        # send file (Pyrogram handles large uploads efficiently)
        await client.send_document(chat_id, file_path, caption=file_path.name)
        await msg.edit_text("✅ Done!")
    except Exception as e:
        logger.exception("Download error")
        await msg.edit_text(f"❌ Error: {e}")
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass

# ========= Main =========
if __name__ == "__main__":
    Path("tmp").mkdir(exist_ok=True)
    logger.info("Bot started.")
    app.run()
