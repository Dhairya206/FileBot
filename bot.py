import os
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from database import init_db
from admin_handlers import verify_admin
from tickets import open_ticket, pay_via_qr
from tools import yt_downloader

TOKEN = "7960003520:AAERf6LxK0aQH7rbkLKjikBBM1UrypNZBBM"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to @dhairya_hu. Send your username and link for approval.")

def main():
    init_db() # Setup tables on Railway
    app = ApplicationBuilder().token(TOKEN).build()

    # Admin
    app.add_handler(CommandHandler("login", verify_admin))
    
    # Subscriptions & Tickets
    app.add_handler(CommandHandler("ticket", open_ticket))
    app.add_handler(CommandHandler("pay_via_qr", pay_via_qr))
    
    # Tools
    app.add_handler(CommandHandler("youtube_download", yt_downloader))

    print("Bot is starting...")
    app.run_polling()

if __name__ == '__main__':
    main()
