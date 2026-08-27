import os
import logging
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web
from bson.objectid import ObjectId
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.error import BadRequest

# ----------------- CONFIGURATION FROM ENVIRONMENT VARIABLES -----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "6406261277:AAFHaNkwP_0PubT96ybFaie6bp50PILjsKk")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "anymovies1_bot") # No @ symbol
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://manisa3233b_db_user:manisa3233b_db_user@cluster0.5euqcbc.mongodb.net/?appName=Cluster0")
STORAGE_CHANNEL_ID = int(os.environ.get("STORAGE_CHANNEL_ID", "-1001663513937"))
UPDATES_CHANNEL_ID = int(os.environ.get("UPDATES_CHANNEL_ID", "-1004343424667"))
UPDATES_CHANNEL_LINK = os.environ.get("UPDATES_CHANNEL_LINK", "https://t.me/+GkqvHaJDgpU4ZTVl")
PORT = int(os.environ.get("PORT", "8080")) # Render assigns this automatically

logging.basicConfig(level=logging.INFO)

# ----------------- MONGODB SETUP -----------------
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["telegram_movie_bot"]
movies_collection = db["movies"]

# ----------------- HANDLERS -----------------

async def index_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-indexes files uploaded to the storage channel into MongoDB."""
    message = update.channel_post
    if not message: return
    media = message.video or message.document
    if not media: return

    file_id = media.file_id
    file_name = getattr(media, 'file_name', None) or message.caption or "Unknown_Movie"
    
    # Insert or update file in MongoDB (prevents duplicates)
    await movies_collection.update_one(
        {"file_id": file_id},
        {"$set": {"file_name": file_name, "file_id": file_id}},
        upsert=True
    )
    logging.info(f"Indexed: {file_name}")

async def search_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Searches MongoDB using regex (fuzzy search) and sends deep link buttons."""
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Usage: `/search <movie_name>`", parse_mode="Markdown")
        return

    # Search MongoDB ignoring case
    cursor = movies_collection.find({"file_name": {"$regex": query, "$options": "i"}}).limit(5)
    results = await cursor.to_list(length=5)

    if not results:
        await update.message.reply_text("❌ No movies found matching your query.")
        return

    keyboard = []
    for doc in results:
        # Convert MongoDB ObjectId to string for the deep link payload
        db_id = str(doc["_id"])
        deep_link_url = f"https://t.me/{BOT_USERNAME}?start={db_id}"
        keyboard.append([InlineKeyboardButton(f"📁 {doc['file_name'][:35]}...", url=deep_link_url)])

    await update.message.reply_text(
        f"🔍 *Results for:* `{query}`\nClick below to get the file in private chat:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks Force Sub and delivers file from MongoDB via PM."""
    user_id = update.effective_user.id
    payload = context.args[0] if context.args else None

    # 1. Force Subscribe Check
    try:
        member = await context.bot.get_chat_member(chat_id=UPDATES_CHANNEL_ID, user_id=user_id)
        is_subscribed = member.status not in ['left', 'kicked']
    except BadRequest:
        is_subscribed = False

    if not is_subscribed:
        keyboard = [[InlineKeyboardButton("📢 Join Updates Channel", url=UPDATES_CHANNEL_LINK)]]
        if payload:
            keyboard.append([InlineKeyboardButton("🔄 Try Again", url=f"https://t.me/{BOT_USERNAME}?start={payload}")])
        
        await update.message.reply_text(
            "🛑 *Access Denied!*\nYou must join our updates channel to download movies.",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return

    # 2. File Delivery
    if payload:
        try:
            doc = await movies_collection.find_one({"_id": ObjectId(payload)})
            if doc:
                await update.message.reply_text(f"🚀 Sending: *{doc['file_name']}*...", parse_mode="Markdown")
                await update.message.reply_document(document=doc['file_id'])
                return
        except Exception as e:
            logging.error(f"Error fetching file: {e}")
            
        await update.message.reply_text("❌ File not found or invalid link.")
        return

    await update.message.reply_text("Welcome! Search for movies inside our group to get files delivered here.")

# ----------------- DUMMY WEB SERVER (FOR CLOUD HOSTING) -----------------
async def health_check(request):
    """Render pings this to ensure the app is alive."""
    return web.Response(text="Bot is running!")

async def run_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

# ----------------- MAIN RUNNER -----------------
async def main():
    # Start web server
    await run_server()
    
    # Start bot
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.CHAT & filters.Chat(STORAGE_CHANNEL_ID), index_channel_post))
    app.add_handler(CommandHandler("search", search_in_group))
    app.add_handler(CommandHandler("start", start_handler))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # Keep running forever
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())