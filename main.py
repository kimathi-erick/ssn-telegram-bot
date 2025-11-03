import os
import uuid
import logging
from datetime import datetime

from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 937017799

app = FastAPI()
bot_app = Application.builder().token(BOT_TOKEN).build()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("RescueBot")

active_tracks = {}

# === /start → Generate Link (Only You) ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Unauthorized.")
        return

    track_id = str(uuid.uuid4())[:8]
    active_tracks[track_id] = update.effective_user.id

    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=help_{track_id}"

    await update.message.reply_text(
        f"**RESCUE LINK READY**\n\n"
        f"Send this:\n`{link}`\n\n"
        f"Anyone who clicks will see a **HUGE button**.\n"
        f"One tap = location sent to you.",
        parse_mode="Markdown"
    )

# === Deep Link: help_XXXX → Auto BIG Button ===
async def help_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or not args[0].startswith("help_"):
        return

    track_id = args[0].split("_", 1)[1]
    if track_id not in active_tracks:
        await update.message.reply_text("Link expired.")
        return

    context.user_data["track_id"] = track_id

    # GIANT BUTTON — fills screen
    keyboard = [
        [InlineKeyboardButton("SEND MY LOCATION NOW", request_location=True)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "EMERGENCY HELP\n\n"
        "TAP THE BIG BUTTON BELOW\n"
        "TO SEND YOUR LOCATION",
        reply_markup=reply_markup
    )

    # Notify you: "Link opened!"
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"LINK OPENED!\nTrack ID: `{track_id}`\nUser: {update.effective_user.full_name}\nWaiting for location..."
    )

# === Location → Send to You ===
async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    track_id = context.user_data.get("track_id")
    if not track_id or track_id not in active_tracks:
        return

    user = update.effective_user
    maps = f"https://maps.google.com/?q={loc.latitude},{loc.longitude}"

    text = (
        f"LOCATION RECEIVED!\n\n"
        f"Track ID: `{track_id}`\n"
        f"Name: {user.full_name}\n"
        f"Username: @{user.username or 'None'}\n"
        f"Time: {datetime.now():%H:%M:%S}\n"
        f"GPS: `{loc.latitude}, {loc.longitude}`\n"
        f"[Open in Maps]({maps})"
    )

    await context.bot.send_location(
        chat_id=active_tracks[track_id],
        latitude=loc.latitude,
        longitude=loc.longitude,
        caption=text,
        parse_mode="Markdown"
    )

    await update.message.reply_text("Location sent. Help is coming.")

# === Webhook & Startup ===
@app.post("/webhook")
async def webhook(request: Request):
    update = Update.de_json(await request.json(), bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}

@app.on_event("startup")
async def startup():
    url = f"https://{os.getenv('RAILWAY_STATIC_URL')}/webhook"
    await bot_app.bot.set_webhook(url=url)
    log.info(f"Webhook: {url}")

@app.get("/")
async def health():
    return {"status": "ready"}

# === Handlers ===
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("start", help_user))
bot_app.add_handler(MessageHandler(filters.LOCATION, location_handler))
