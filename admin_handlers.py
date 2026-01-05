import os
from telegram import Update
from telegram.ext import ContextTypes
from database import session, User, FileMetadata
import datetime

# The secret one-time code you specified
SECRET_ENTRY_CODE = "2008"

async def admin_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """One-time admin access logic."""
    user_id = update.effective_user.id
    
    # Check if a code was provided: /admin 2008
    if not context.args or context.args[0] != SECRET_ENTRY_CODE:
        await update.message.reply_text("❌ Access Denied: Invalid or missing code.")
        return

    # Check if user already exists in DB
    user = session.query(User).filter_by(tg_id=user_id).first()
    
    if user:
        user.is_admin = True
        # Set expiry to 1 year from now as per your requirement
        user.plan_expiry = datetime.datetime.now() + datetime.timedelta(days=365)
        session.commit()
        await update.message.reply_text("✅ Admin access granted. Valid for 1 year.")
    else:
        await update.message.reply_text("❌ Error: You must /start the bot first to register your ID.")

async def add_user_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /adduser @username monthly"""
    admin = session.query(User).filter_by(tg_id=update.effective_user.id).first()
    if not admin or not admin.is_admin:
        return # Silently ignore non-admins

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /adduser @username <plan_type>")
        return

    target_username = context.args[0].replace("@", "")
    plan_type = context.args[1].lower()
    
    # Plan logic mapping
    plans = {
        "monthly": {"limit": 5.0, "days": 30},
        "quarterly": {"limit": 15.0, "days": 90},
        "halfyearly": {"limit": 30.0, "days": 180},
        "yearly": {"limit": 100.0, "days": 365}
    }

    if plan_type not in plans:
        await update.message.reply_text("Invalid plan. Choose: monthly, quarterly, halfyearly, yearly")
        return

    user = session.query(User).filter_by(username=target_username).first()
    if user:
        user.is_approved = True
        user.storage_limit = plans[plan_type]["limit"]
        user.plan_expiry = datetime.datetime.now() + datetime.timedelta(days=plans[plan_type]["days"])
        session.commit()
        await update.message.reply_text(f"✅ User @{target_username} activated with {user.storage_limit}GB.")
        # Notify the user
        await context.bot.send_message(chat_id=user.tg_id, text="🎉 Your subscription has been activated!")
    else:
        await update.message.reply_text("User not found in database.")

async def view_user_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /viewstorage @username"""
    # ... Logic to query FileMetadata for the specific user and list files ...
    await update.message.reply_text("Fetching user storage details...")
