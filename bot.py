from telegram.ext import Updater, CommandHandler
import tickets
import admin_handlers
import tools

TOKEN = "YOUR_BOT_TOKEN_HERE"

def start(update, context):
    update.message.reply_text("Welcome to Railway Bot! Use /ticket to report an issue.")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("ticket", tickets.handle_ticket_creation))
    dp.add_handler(CommandHandler("viewtickets", tickets.view_tickets))
    dp.add_handler(CommandHandler("broadcast", admin_handlers.admin_broadcast))

    print("Bot is running...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
