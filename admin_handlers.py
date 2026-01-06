import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from database import Database
from cryptography.fernet import Fernet
import asyncio

logger = logging.getLogger(__name__)
db = Database()

# Admin IDs from environment
ADMIN_ID = int(os.getenv('ADMIN_ID'))
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Secret commands (only work in admin DMs)
async def secret_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Secret admin panel accessible only via DM"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Access denied. This command is for admin only.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 View All Users", callback_data="admin_view_users")],
        [InlineKeyboardButton("🎫 Active Tickets", callback_data="admin_view_tickets")],
        [InlineKeyboardButton("📈 Storage Stats", callback_data="admin_storage_stats")],
        [InlineKeyboardButton("🔒 Add New User", callback_data="admin_add_user")],
        [InlineKeyboardButton("⏰ Check Expirations", callback_data="admin_check_expiry")],
        [InlineKeyboardButton("💾 Backup Database", callback_data="admin_backup_db")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔐 **Admin Secret Panel**\n\n"
        "Select an option below:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add user with subscription: /adduser @username monthly"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only command.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/adduser @username plan_type`\n"
            "Plans: `monthly`, `quarterly`, `semiannual`, `yearly`",
            parse_mode='Markdown'
        )
        return
    
    username = context.args[0].replace('@', '')
    plan_type = context.args[1].lower()
    
    # Get user from database
    user = db.get_user_by_username(username)
    if not user:
        await update.message.reply_text(f"❌ User @{username} not found in database.")
        return
    
    # Calculate expiry based on plan
    plan_durations = {
        'monthly': 30,
        'quarterly': 90,
        'semiannual': 180,
        'yearly': 365
    }
    
    if plan_type not in plan_durations:
        await update.message.reply_text(
            "❌ Invalid plan type. Use: monthly, quarterly, semiannual, yearly"
        )
        return
    
    days = plan_durations[plan_type]
    expiry_date = datetime.now() + timedelta(days=days)
    
    # Update user subscription
    db.update_user_subscription(user['id'], plan_type, expiry_date, is_active=True)
    
    # Generate storage limit based on plan
    storage_limits = {
        'monthly': 5 * 1024 * 1024 * 1024,  # 5GB
        'quarterly': 15 * 1024 * 1024 * 1024,  # 15GB
        'semiannual': 30 * 1024 * 1024 * 1024,  # 30GB
        'yearly': 100 * 1024 * 1024 * 1024  # 100GB
    }
    storage_limit = storage_limits[plan_type]
    db.update_user_storage_limit(user['id'], storage_limit)
    
    # Notify user
    try:
        await context.bot.send_message(
            chat_id=user['telegram_id'],
            text=f"✅ **Subscription Activated!**\n\n"
                 f"Your {plan_type} plan has been activated.\n"
                 f"📅 Expires: {expiry_date.strftime('%Y-%m-%d')}\n"
                 f"💾 Storage: {storage_limit // (1024**3)}GB\n\n"
                 f"You can now use all features with `/start`"
        )
    except:
        pass
    
    await update.message.reply_text(
        f"✅ User @{username} added with {plan_type} plan.\n"
        f"Expires: {expiry_date.strftime('%Y-%m-%d')}\n"
        f"Storage: {storage_limit // (1024**3)}GB"
    )

async def view_storage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View user storage: /viewstorage @username"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/viewstorage @username`", parse_mode='Markdown')
        return
    
    username = context.args[0].replace('@', '')
    user = db.get_user_by_username(username)
    
    if not user:
        await update.message.reply_text(f"❌ User @{username} not found.")
        return
    
    # Get user's files info
    files_info = db.get_user_files_info(user['id'])
    total_size = files_info.get('total_size', 0)
    file_count = files_info.get('file_count', 0)
    
    used_gb = total_size / (1024**3)
    limit_gb = user['storage_limit'] / (1024**3) if user['storage_limit'] else 0
    usage_percent = (used_gb / limit_gb * 100) if limit_gb > 0 else 0
    
    status = "✅ Active" if user['subscription_active'] else "❌ Inactive"
    expiry = user['subscription_expiry'].strftime('%Y-%m-%d') if user['subscription_expiry'] else "Never"
    
    await update.message.reply_text(
        f"📊 **Storage Report for @{username}**\n\n"
        f"👤 User ID: `{user['telegram_id']}`\n"
        f"📈 Status: {status}\n"
        f"📅 Expiry: {expiry}\n"
        f"📦 Plan: {user['subscription_plan'] or 'None'}\n\n"
        f"📁 Files: {file_count}\n"
        f"💾 Used: {used_gb:.2f}GB / {limit_gb:.0f}GB\n"
        f"📊 Usage: {usage_percent:.1f}%\n\n"
        f"🆔 Database ID: `{user['id']}`",
        parse_mode='Markdown'
    )

async def download_user_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download user file: /download @username filename"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only command.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/download @username filename`", parse_mode='Markdown')
        return
    
    username = context.args[0].replace('@', '')
    filename = ' '.join(context.args[1:])
    
    user = db.get_user_by_username(username)
    if not user:
        await update.message.reply_text(f"❌ User @{username} not found.")
        return
    
    # Get file from database
    file_record = db.get_user_file_by_name(user['id'], filename)
    if not file_record:
        await update.message.reply_text(f"❌ File '{filename}' not found for @{username}.")
        return
    
    # Decrypt file data (simplified - actual decryption depends on your implementation)
    try:
        # For now, send file info
        await update.message.reply_text(
            f"📄 **File Information**\n\n"
            f"👤 User: @{username}\n"
            f"📁 Filename: `{file_record['filename']}`\n"
            f"📦 Size: {file_record['file_size'] / 1024:.1f}KB\n"
            f"📅 Uploaded: {file_record['uploaded_at'].strftime('%Y-%m-%d %H:%M')}\n"
            f"🔐 Encrypted: {file_record['is_encrypted']}\n\n"
            f"🆔 File ID: `{file_record['id']}`",
            parse_mode='Markdown'
        )
        
        # Note: Actual file download would involve decrypting and sending the file
        # This requires your encryption implementation
        await update.message.reply_text(
            "⚠️ File download decryption not implemented in this example. "
            "Check the file record above for details."
        )
        
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def close_ticket_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close a ticket: /closeticket ticket_id"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/closeticket ticket_id`", parse_mode='Markdown')
        return
    
    ticket_id = context.args[0]
    ticket = db.get_ticket(ticket_id)
    
    if not ticket:
        await update.message.reply_text(f"❌ Ticket {ticket_id} not found.")
        return
    
    if ticket['status'] == 'closed':
        await update.message.reply_text(f"⚠️ Ticket {ticket_id} is already closed.")
        return
    
    db.update_ticket_status(ticket_id, 'closed')
    
    # Notify user
    try:
        await context.bot.send_message(
            chat_id=ticket['user_id'],
            text=f"🎫 **Ticket #{ticket_id} Closed**\n\n"
                 f"Your payment ticket has been closed by admin.\n"
                 f"If you have any questions, use /contact"
        )
    except:
        pass
    
    await update.message.reply_text(f"✅ Ticket {ticket_id} closed successfully.")

async def view_tickets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all tickets: /tickets [status]"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only command.")
        return
    
    status_filter = context.args[0] if context.args else 'open'
    
    tickets = db.get_tickets_by_status(status_filter)
    
    if not tickets:
        await update.message.reply_text(f"No {status_filter} tickets found.")
        return
    
    tickets_text = f"🎫 **{status_filter.upper()} Tickets**\n\n"
    
    for ticket in tickets[:10]:  # Show first 10 tickets
        user = db.get_user_by_id(ticket['user_id'])
        username = f"@{user['username']}" if user and user['username'] else f"User {ticket['user_id']}"
        
        tickets_text += (
            f"🆔 #{ticket['id']}\n"
            f"👤 {username}\n"
            f"📅 Created: {ticket['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
            f"📝 Type: {ticket['ticket_type']}\n"
            f"---\n"
        )
    
    await update.message.reply_text(tickets_text, parse_mode='Markdown')

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin panel callbacks"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        await query.edit_message_text("⛔ Access denied.")
        return
    
    data = query.data
    
    if data == "admin_view_users":
        users = db.get_all_users()
        if not users:
            await query.edit_message_text("No users found.")
            return
        
        text = "👥 **All Users**\n\n"
        for user in users[:15]:  # Show first 15 users
            status = "✅" if user['subscription_active'] else "❌"
            expiry = user['subscription_expiry'].strftime('%Y-%m-%d') if user['subscription_expiry'] else "None"
            text += f"{status} @{user['username']} - {user['subscription_plan'] or 'None'} (Exp: {expiry})\n"
        
        await query.edit_message_text(text, parse_mode='Markdown')
    
    elif data == "admin_view_tickets":
        tickets = db.get_tickets_by_status('open')
        if not tickets:
            await query.edit_message_text("No open tickets.")
            return
        
        text = "🎫 **Open Tickets**\n\n"
        for ticket in tickets[:10]:
            user = db.get_user_by_id(ticket['user_id'])
            username = f"@{user['username']}" if user else f"ID:{ticket['user_id']}"
            text += f"🆔 #{ticket['id']} - {username} - {ticket['ticket_type']}\n"
        
        await query.edit_message_text(text, parse_mode='Markdown')
    
    elif data == "admin_backup_db":
        await query.edit_message_text("💾 Database backup initiated...")
        # Implement backup logic here
        await asyncio.sleep(1)
        await query.edit_message_text("✅ Database backup completed (simulated).")
    
    elif data == "admin_add_user":
        await query.edit_message_text(
            "To add a user, use the command:\n"
            "`/adduser @username plan_type`\n\n"
            "Plan types: monthly, quarterly, semiannual, yearly",
            parse_mode='Markdown'
        )

async def handle_admin_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin direct messages for secret commands"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        return
    
    message_text = update.message.text
    if message_text and message_text.startswith('/'):
        # Let other handlers process commands
        return
    
    # If it's just a message (not a command), show admin panel
    await secret_admin_panel(update, context)

def setup_admin_handlers(application):
    """Setup all admin command handlers"""
    
    # Secret admin commands (only in DMs)
    application.add_handler(CommandHandler("adduser", add_user_command))
    application.add_handler(CommandHandler("viewstorage", view_storage_command))
    application.add_handler(CommandHandler("download", download_user_file))
    application.add_handler(CommandHandler("closeticket", close_ticket_command))
    application.add_handler(CommandHandler("tickets", view_tickets_command))
    
    # Admin panel callback handler
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    
    # Admin DM handler (for non-command messages)
    admin_filter = filters.User(user_id=ADMIN_ID) & filters.ChatType.PRIVATE
    application.add_handler(MessageHandler(admin_filter & filters.TEXT & ~filters.COMMAND, handle_admin_dm))
    
    logger.info("Admin handlers setup complete")