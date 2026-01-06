import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from database import init_db, get_conn
import tickets, admin_handlers, media_tools

TOKEN = "7960003520:AAERf6LxK0aQH7rbkLKjikBBM1UrypNZBBM"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to @dhairya_hu Storage Bot!")

async def auth_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == "2008":
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_admin=True WHERE user_id=%s", (update.effective_user.id,))
        conn.commit()
        await update.message.reply_text("Admin access granted.")

if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", auth_admin))
    app.add_handler(CommandHandler("ticket", tickets.create_ticket))
    app.add_handler(CallbackQueryHandler(tickets.close_ticket_cb, pattern="^close_"))
    app.add_handler(CommandHandler("adduser", admin_handlers.add_user_cmd))
    app.add_handler(CommandHandler("viewstorage", admin_handlers.view_user_storage))
    
    app.run_polling()
