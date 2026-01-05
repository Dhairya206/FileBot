import os
import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv

# Import our custom modules
from database import init_db, session, User
from admin_handlers import admin_auth, add_user_subscription
from tickets import create_ticket, pay_via_qr, close_ticket
from tools import download_youtube_video, images_to_pdf

# Load credentials from Railway Environment Variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Basic logging to see errors in Railway's console
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update, context):
    """Initializes user in DB and explains the bot."""
    user = update.effective_user
    # Save user to DB if not exists
    db_user = session.query(User).filter_by(tg_id=user.id).first()
    if not db_user:
        new_user = User(tg_id=user.id, username=user.username)
        session.add(new_user)
        session.commit()
    
    await update.message.reply_text(
        f"Hi @{user.username}! Welcome to @dhairya_hu Storage Bot.\n\n"
        "1. Send your profile link for approval.\n"
        "2. View /plans to see storage tiers.\n"
        "3. Open a /ticket for payment."
    )

if __name__ == '__main__':
    # Initialize the PostgreSQL Database tables
    init_db()
    
    # Build the application
    app = ApplicationBuilder().token(TOKEN).build()

    # COMMAND HANDLERS
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_auth))
    app.add_handler(CommandHandler("plans", lambda u, c: u.message.reply_text("Plans: ₹25 (5GB), ₹60 (15GB), ₹125 (30GB), ₹275 (100GB)")))
    app.add_handler(CommandHandler("ticket", create_ticket))
    app.add_handler(CommandHandler("pay_via_qr", pay_via_qr))
    app.add_handler(CommandHandler("adduser", add_user_subscription))
    app.add_handler(CommandHandler("closeticket", close_ticket))

    # Start the Bot
    print("Bot is alive and running on Railway...")
    app.run_polling()
