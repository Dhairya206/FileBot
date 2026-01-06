from telegram import Update
from telegram.ext import ContextTypes
from database import get_conn
import datetime

ADMIN_ID = 7960003520

async def add_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        uname = context.args[0].replace("@", "")
        plan = context.args[1]
        expiry = datetime.datetime.now() + datetime.timedelta(days=30)
        
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_approved=True, plan=%s, expiry_date=%s WHERE username=%s", (plan, expiry, uname))
        conn.commit()
        await update.message.reply_text(f"✅ @{uname} approved on {plan} plan.")
    except:
        await update.message.reply_text("Usage: /adduser @username monthly")

async def view_user_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    uname = context.args[0].replace("@", "")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT f.file_name FROM files f JOIN users u ON f.user_id=u.user_id WHERE u.username=%s", (uname,))
    files = cur.fetchall()
    await update.message.reply_text(f"Files: {str(files)}")
