import os
import uuid
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required in Railway variables")

OWNER_ID = 937017799 # REPLACE WITH YOUR TELEGRAM USER ID

# === LOGGING ===
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("RescueBot")

# === TELEGRAM APP ===
bot_app = Application.builder().token(BOT_TOKEN).build()

# === IN-MEMORY TRACKING (Railway is stateless) ===
active_tracks = {}  # {track_id: owner_id}


# === /start → Generate Tracking Link (Owner Only) ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Unauthorized access.")
        return

    track_id = str(uuid.uuid4())[:8]
    active_tracks[track_id] = OWNER_ID

    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=help_{track_id}"

    await update.message.reply_text(
        f"**RESCUE LINK GENERATED**\n\n"
        f"Share this link:\n\n"
        f"`{link}`\n\n"
        f"Anyone who clicks will be asked to share location.\n"
        f"You will receive live GPS instantly.",
        parse_mode="Markdown"
    )
    log.info(f"Tracking link generated: {link}")


# === Deep Link: help_XXXX → Auto Show BIG Location Button ===
async def help_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or not args[0].startswith("help_"):
        return

    track_id = args[0].split("_", 1)[1]
    if track_id not in active_tracks:
        await update.message.reply_text("This link is invalid or expired.")
        return

    context.user_data["track_id"] = track_id

    # GIANT BUTTON – fills screen
    keyboard = [[InlineKeyboardButton("SEND MY LOCATION NOW", request_location=True)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "EMERGENCY HELP NEEDED\n\n"
        "TAP THE BIG BUTTON BELOW\n"
        "TO SEND YOUR CURRENT LOCATION",
        reply_markup=reply_markup
    )

    # Notify owner: link opened
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"LINK OPENED!\n\n"
             f"Track ID: `{track_id}`\n"
             f"User: {update.effective_user.full_name}\n"
             f"Username: @{update.effective_user.username or 'None'}\n"
             f"Waiting for location...",
        parse_mode="Markdown"
    )


# === Location Received → Forward to Owner ===
async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    track_id = context.user_data.get("track_id")
    if not track_id or track_id not in active_tracks:
        return

    user = update.effective_user
    owner_id = active_tracks[track_id]
    maps_url = f"https://maps.google.com/?q={loc.latitude},{loc.longitude}"

    text = (
        f"LOCATION RECEIVED!\n\n"
        f"Track ID: `{track_id}`\n"
        f"Name: {user.full_name}\n"
        f"Username: @{user.username or 'None'}\n"
        f"User ID: `{user.id}`\n"
        f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"GPS: `{loc.latitude}, {loc.longitude}`\n"
        f"[Open in Google Maps]({maps_url})"
    )

    await context.bot.send_location(
        chat_id=owner_id,
        latitude=loc.latitude,
        longitude=loc.longitude,
        caption=text,
        parse_mode="Markdown"
    )

    await update.message.reply_text("Location sent. Help is on the way.")

    # Optional: auto-remove after first use
    # del active_tracks[track_id]


# === FASTAPI APP WITH LIFESPAN (NO DEPRECATION) ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- STARTUP: Set Webhook ----
    webhook_url = f"https://{os.getenv('RAILWAY_STATIC_URL')}/webhook"
    await bot_app.bot.set_webhook(url=webhook_url)
    log.info(f"Webhook set: {webhook_url}")

    yield  # App runs here

    # ---- SHUTDOWN: Clean up ----
    await bot_app.bot.delete_webhook(drop_pending_updates=True)
    log.info("Webhook removed – bot stopped.")


app = FastAPI(lifespan=lifespan)


# === WEBHOOK ENDPOINT ===
@app.post("/webhook")
async def webhook(request: Request):
    json_data = await request.json()
    update = Update.de_json(json_data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}


# === HEALTH CHECK ===
@app.get("/")
async def health():
    return {"status": "running", "bot": "RescueLink"}


# === REGISTER HANDLERS ===
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("start", help_user))  # Handles deep links
bot_app.add_handler(MessageHandler(filters.LOCATION, location_handler))
