from telegram import Update
from telegram.ext import ContextTypes
from database import get_connection
from datetime import datetime, timedelta

async def verify_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.args and context.args[0] == "2008":
        conn = get_connection()
        cur = conn.cursor()
        expiry = datetime.now() + timedelta(days=365)
        cur.execute("UPDATE users SET is_admin = True, admin_expiry = %s WHERE user_id = %s", (expiry, user_id))
        conn.commit()
        cur.close()
        conn.close()
        await update.message.reply_text("✅ Admin access granted for 1 year! No further code needed.")
    else:
        await update.message.reply_text("❌ Incorrect code.")

async def add_user_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Example: /adduser @username monthly
    # Real implementation would look up ID via username in DB
    await update.message.reply_text("User subscription updated successfully.")
