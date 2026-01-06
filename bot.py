import os
import logging
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
)
from database import Database, init_db
from admin_handlers import setup_admin_handlers
from tickets import setup_ticket_handlers
from tools import setup_tools_handlers

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global variables
ADMIN_ID = int(os.getenv('ADMIN_ID'))
BOT_TOKEN = os.getenv('BOT_TOKEN')
SECRET_CODE = os.getenv('SECRET_CODE', '2008')

# Database instance
db = Database()

# Conversation states for user registration
SECRET_CODE_INPUT, USERNAME_INPUT, PROFILE_LINK_INPUT = range(3)

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    user_id = user.id
#    
#    # Check if user exists in database
#    user_data = db.get_user(user_id)
#    
#    if not user_data:
#        # New user - start registration process
#        context.user_data['registration'] = {
#            'telegram_id': user_id,
            'username': user.username
        }
        
        
        await update.message.reply_text(
            "🔐 **Welcome to TheFilex Bot**\n\n"
            "This is a secure, subscription-based file storage system.\n\n"
            "To begin registration, please send the **secret code**.\n"
            f"*Note:* The secret code is valid until {SECRET_CODE_EXPIRY.strftime('%Y-%m-%d')}",
            parse_mode='Markdown'
        )
        return SECRET_CODE_INPUT
    
    elif not user_data['is_approved']:
        # User exists but not approved
        await update.message.reply_text(
            "⏳ **Awaiting Approval**\n\n"
            "Your registration is pending admin approval.\n"
            "Please wait while we review your application.\n\n"
            "You will be notified once approved.",
            parse_mode='Markdown'
        )
        return
    
    elif not user_data['subscription_active']:
        # User approved but no active subscription
        keyboard = [
            [InlineKeyboardButton("📋 View Plans", callback_data="view_plans")],
            [InlineKeyboardButton("🎫 Create Payment Ticket", callback_data="create_ticket")],
            [InlineKeyboardButton("📞 Contact Support", callback_data="contact_support")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "✅ **Registration Approved**\n\n"
            "Your account has been approved by admin.\n"
            "However, you don't have an active subscription.\n\n"
            "Please choose a plan to start using the service:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    else:
        # User has active subscription - show main menu
        await show_main_menu(update, context)

async def secret_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle secret code input"""
    user_input = update.message.text.strip()
    
    if user_input != SECRET_CODE:
        await update.message.reply_text(
            "❌ **Invalid Secret Code**\n\n"
            "Please check the code and try again.\n"
            "If you don't have a valid code, you cannot register at this time.",
            parse_mode='Markdown'
        )
        return SECRET_CODE_INPUT
    
    # Valid secret code
    await update.message.reply_text(
        "✅ **Secret Code Verified**\n\n"
        "Now, please send your **Telegram username** (with @).\n"
        "Example: @yourusername",
        parse_mode='Markdown'
    )
    return USERNAME_INPUT

async def username_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle username input"""
    username = update.message.text.strip()
    
    if not username.startswith('@'):
        await update.message.reply_text(
            "❌ **Invalid Format**\n\n"
            "Please send your username starting with @.\n"
            "Example: @yourusername",
            parse_mode='Markdown'
        )
        return USERNAME_INPUT
    
    context.user_data['registration']['username'] = username
    
    await update.message.reply_text(
        "📎 **Profile Link Required**\n\n"
        "Now, please send your **Telegram profile link**.\n"
        "You can get this by sharing your profile in Telegram.\n\n"
        "Example: https://t.me/yourusername",
        parse_mode='Markdown'
    )
    return PROFILE_LINK_INPUT

async def profile_link_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle profile link input"""
    profile_link = update.message.text.strip()
    
    # Basic URL validation
    if not profile_link.startswith('https://t.me/'):
        await update.message.reply_text(
            "❌ **Invalid Profile Link**\n\n"
            "Please send a valid Telegram profile link.\n"
            "It should start with: https://t.me/\n\n"
            "Example: https://t.me/yourusername",
            parse_mode='Markdown'
        )
        return PROFILE_LINK_INPUT
    
    # Complete registration
    registration_data = context.user_data['registration']
    
    # Add user to database
    user_id = db.add_user(
        telegram_id=registration_data['telegram_id'],
        username=registration_data['username'].replace('@', ''),
        profile_link=profile_link
    )
    
    if user_id:
        # Mark secret code as used
        db.update_user_secret_code(registration_data['telegram_id'])
        
        # Notify admin
        try:
            bot = context.bot
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=f"👤 **New Registration**\n\n"
                     f"Username: {registration_data['username']}\n"
                     f"Profile: {profile_link}\n"
                     f"User ID: {registration_data['telegram_id']}\n"
                     f"Database ID: {user_id}\n\n"
                     f"Use `/approve {registration_data['telegram_id']}` to approve.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
        
        await update.message.reply_text(
            "✅ **Registration Complete**\n\n"
            "Your information has been submitted for admin approval.\n"
            "You will be notified once your account is approved.\n\n"
            "Please wait for the approval notification.",
            parse_mode='Markdown'
        )
        
        # Clear registration data
        context.user_data.pop('registration', None)
        
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "❌ **Registration Failed**\n\n"
            "An error occurred during registration.\n"
            "Please try again or contact support.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the registration process"""
    context.user_data.pop('registration', None)
    await update.message.reply_text(
        "Registration cancelled.\n"
        "You can start again with /start",
        parse_mode='Markdown'
    )
    return ConversationHandler.END

# Main menu and commands
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu for subscribed users"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data or not user_data['subscription_active']:
        await update.message.reply_text(
            "You need an active subscription to use this feature.\n"
            "Use /plans to view available plans."
        )
        return
    
    keyboard = [
        [
            InlineKeyboardButton("📁 Upload", callback_data="upload_menu"),
            InlineKeyboardButton("📂 My Files", callback_data="my_files")
        ],
        [
            InlineKeyboardButton("🎥 YouTube Tools", callback_data="youtube_tools"),
            InlineKeyboardButton("📄 PDF Tools", callback_data="pdf_tools")
        ],
        [
            InlineKeyboardButton("📊 My Stats", callback_data="my_stats"),
            InlineKeyboardButton("💳 My Plan", callback_data="my_plan")
        ],
        [
            InlineKeyboardButton("🆘 Help", callback_data="help"),
            InlineKeyboardButton("📞 Contact", callback_data="contact")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📦 **TheFilex Bot - Main Menu**\n\n"
        "Select an option below:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /plans command"""
    keyboard = [
        [InlineKeyboardButton("💰 Monthly - ₹25 (5GB)", callback_data="plan_monthly")],
        [InlineKeyboardButton("💰 Quarterly - ₹60 (15GB)", callback_data="plan_quarterly")],
        [InlineKeyboardButton("💰 Semi-Annual - ₹125 (30GB)", callback_data="plan_semiannual")],
        [InlineKeyboardButton("💰 Annual - ₹275 (100GB)", callback_data="plan_yearly")],
        [InlineKeyboardButton("🎫 Create Payment Ticket", callback_data="create_ticket")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "💰 **Subscription Plans**\n\n"
        "1. **Monthly Plan**\n"
        "   • Price: ₹25/month\n"
        "   • Storage: 5GB\n"
        "   • Features: All basic features\n\n"
        "2. **Quarterly Plan**\n"
        "   • Price: ₹60/3 months\n"
        "   • Storage: 15GB\n"
        "   • Features: All basic features + priority support\n\n"
        "3. **Semi-Annual Plan**\n"
        "   • Price: ₹125/6 months\n"
        "   • Storage: 30GB\n"
        "   • Features: All features + faster processing\n\n"
        "4. **Annual Plan**\n"
        "   • Price: ₹275/year\n"
        "   • Storage: 100GB\n"
        "   • Features: All premium features + dedicated support\n\n"
        "To subscribe, create a payment ticket:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /contact command"""
    await update.message.reply_text(
        "📞 **Contact Support**\n\n"
        "For any issues, questions, or support:\n\n"
        "1. Use the /ticket command for payment-related issues\n"
        "2. Send a direct message to admin (may take 24-48 hours)\n"
        "3. Check /help for common solutions\n\n"
        "⚠️ **Note:** Always include your username and issue details when contacting support.",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    await update.message.reply_text(
        "🆘 **Help & Commands**\n\n"
        "**Account Commands:**\n"
        "/start - Start the bot\n"
        "/plans - View subscription plans\n"
        "/mystats - View your storage statistics\n"
        "/myplan - View your current plan\n"
        "/contact - Contact support\n\n"
        "**File Management:**\n"
        "/upload_docs - Upload documents\n"
        "/upload_images - Upload images\n"
        "/upload_videos - Upload videos\n"
        "/upload_audio - Upload audio files\n"
        "/myfiles - View all your files\n"
        "/mydocs - View your documents\n"
        "/myimages - View your images\n"
        "/send_docs - Send documents to other users\n"
        "/send_images - Send images to other users\n\n"
        "**YouTube Tools:**\n"
        "/youtube_download - Download YouTube videos\n"
        "/youtube_audio - Extract audio from YouTube\n"
        "/youtube_slides - Create slides from YouTube video\n\n"
        "**PDF Tools:**\n"
        "/create_pdf - Create PDF from photos\n\n"
        "**Payment & Tickets:**\n"
        "/ticket - Create payment ticket\n"
        "/pay_via_qr - Pay via QR code\n\n"
        "For more details on each command, send the command or check the menu.",
        parse_mode='Markdown'
    )

async def my_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mystats command"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("User not found. Please use /start first.")
        return
    
    # Get file statistics
    files_info = db.get_user_files_info(user_data['id'])
    total_size = files_info.get('total_size', 0)
    file_count = files_info.get('file_count', 0)
    
    # Calculate storage usage
    used_gb = total_size / (1024**3)
    limit_gb = user_data['storage_limit'] / (1024**3) if user_data['storage_limit'] else 0
    usage_percent = (used_gb / limit_gb * 100) if limit_gb > 0 else 0
    
    # Create storage bar
    bar_length = 20
    filled_length = int(bar_length * usage_percent / 100)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    
    status = "✅ Active" if user_data['subscription_active'] else "❌ Inactive"
    expiry = user_data['subscription_expiry'].strftime('%Y-%m-%d') if user_data['subscription_expiry'] else "Never"
    
    await update.message.reply_text(
        f"📊 **Your Statistics**\n\n"
        f"👤 Username: @{user_data['username']}\n"
        f"📈 Status: {status}\n"
        f"📅 Expiry: {expiry}\n"
        f"📦 Plan: {user_data['subscription_plan'] or 'None'}\n\n"
        f"📁 Files: {file_count}\n"
        f"💾 Storage: {used_gb:.2f}GB / {limit_gb:.0f}GB\n"
        f"📊 Usage: {usage_percent:.1f}%\n"
        f"[{bar}]\n\n"
        f"📋 File Types:\n",
        parse_mode='Markdown'
    )
    
    # Add file type breakdown
    type_breakdown = files_info.get('type_breakdown', [])
    if type_breakdown:
        breakdown_text = ""
        for item in type_breakdown:
            size_mb = item['size'] / (1024**2) if item['size'] else 0
            breakdown_text += f"  • {item['file_type']}: {item['count']} files ({size_mb:.1f}MB)\n"
        
        await update.message.reply_text(breakdown_text)

async def my_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /myplan command"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("User not found. Please use /start first.")
        return
    
    if not user_data['subscription_active']:
        keyboard = [[InlineKeyboardButton("View Plans", callback_data="view_plans")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ **No Active Subscription**\n\n"
            "You don't have an active subscription.\n"
            "Please choose a plan to continue using the service.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    # Calculate days remaining
    if user_data['subscription_expiry']:
        days_left = (user_data['subscription_expiry'] - datetime.now()).days
        days_text = f"{days_left} days remaining"
        
        if days_left <= 3:
            days_text = f"⚠️ {days_left} days remaining - Renew soon!"
        elif days_left <= 0:
            days_text = "❌ EXPIRED - Please renew"
    else:
        days_text = "No expiry date"
    
    await update.message.reply_text(
        f"💳 **Your Subscription Plan**\n\n"
        f"📋 Plan: **{user_data['subscription_plan']}**\n"
        f"📅 Expiry: {user_data['subscription_expiry'].strftime('%Y-%m-%d') if user_data['subscription_expiry'] else 'Never'}\n"
        f"⏳ Status: {days_text}\n"
        f"💾 Storage: {user_data['storage_limit'] // (1024**3)}GB total\n"
        f"📊 Used: {user_data['storage_used'] / (1024**3):.2f}GB\n"
        f"📈 Available: {(user_data['storage_limit'] - user_data['storage_used']) / (1024**3):.2f}GB\n\n"
        f"To renew or upgrade, use /plans",
        parse_mode='Markdown'
    )

# Callback query handler for main menu
async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "view_plans":
        await plans_command(update, context)
    
    elif data == "create_ticket":
        # Import tickets module function
        from tickets import create_ticket_command
        await create_ticket_command(update, context)
    
    elif data == "upload_menu":
        keyboard = [
            [InlineKeyboardButton("📄 Documents", callback_data="upload_docs")],
            [InlineKeyboardButton("🖼️ Images", callback_data="upload_images")],
            [InlineKeyboardButton("🎬 Videos", callback_data="upload_videos")],
            [InlineKeyboardButton("🎵 Audio", callback_data="upload_audio")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "📁 **Upload Files**\n\n"
            "Select file type to upload:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data == "my_files":
        # Import file management function
        from tools import my_files_command
        await my_files_command(update, context)
    
    elif data == "youtube_tools":
        keyboard = [
            [InlineKeyboardButton("📥 Download Video", callback_data="yt_download")],
            [InlineKeyboardButton("🎵 Extract Audio", callback_data="yt_audio")],
            [InlineKeyboardButton("🖼️ Create Slides", callback_data="yt_slides")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎥 **YouTube Tools**\n\n"
            "Select an option:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data in ["plan_monthly", "plan_quarterly", "plan_semiannual", "plan_yearly"]:
        plan_map = {
            "plan_monthly": "monthly",
            "plan_quarterly": "quarterly", 
            "plan_semiannual": "semiannual",
            "plan_yearly": "yearly"
        }
        
        plan_type = plan_map[data]
        
        # Create ticket for selected plan
        user_data = db.get_user(user_id)
        if user_data:
            from tickets import create_ticket_for_plan
            await create_ticket_for_plan(update, context, user_data['id'], plan_type)
    
    elif data == "back_to_main":
        await show_main_menu(update, context)
    
    else:
        await query.edit_message_text("Functionality coming soon!")

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    # Notify admin about critical errors
    try:
        error_msg = f"Bot Error: {context.error}\nUpdate: {update}"
        await context.bot.send_message(chat_id=ADMIN_ID, text=error_msg[:4000])
    except:
        pass

# Subscription expiry check (scheduled task)
async def check_subscription_expiry(context: ContextTypes.DEFAULT_TYPE):
    """Check for expiring subscriptions and send reminders"""
    logger.info("Checking subscription expiry...")
    
    # Get users with subscriptions expiring in 3 days
    expiring_users = db.get_expiring_subscriptions(days=3)
    
    for user in expiring_users:
        try:
            await context.bot.send_message(
                chat_id=user['telegram_id'],
                text=f"⚠️ **Subscription Reminder**\n\n"
                     f"Your subscription expires in 3 days ({user['subscription_expiry'].strftime('%Y-%m-%d')}).\n"
                     f"Please renew your plan to continue using the service.\n\n"
                     f"Use /plans to view available plans.\n"
                     f"Use /ticket to create a payment ticket.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send expiry reminder to user {user['id']}: {e}")

# Setup bot commands menu
async def post_init(application: Application):
    """Set up bot commands menu"""
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("plans", "View subscription plans"),
        BotCommand("mystats", "View your storage statistics"),
        BotCommand("myplan", "View your current plan"),
        BotCommand("upload_docs", "Upload documents"),
        BotCommand("upload_images", "Upload images"),
        BotCommand("upload_videos", "Upload videos"),
        BotCommand("upload_audio", "Upload audio files"),
        BotCommand("myfiles", "View all your files"),
        BotCommand("mydocs", "View your documents"),
        BotCommand("myimages", "View your images"),
        BotCommand("youtube_download", "Download YouTube videos"),
        BotCommand("youtube_audio", "Extract audio from YouTube"),
        BotCommand("youtube_slides", "Create slides from YouTube video"),
        BotCommand("create_pdf", "Create PDF from photos"),
        BotCommand("ticket", "Create payment ticket"),
        BotCommand("pay_via_qr", "Pay via QR code"),
        BotCommand("contact", "Contact support"),
        BotCommand("help", "Help & commands list")
    ]
    
    await application.bot.set_my_commands(commands)

def main():
    """Main function to run the bot"""
    # Initialize database
    init_db()
    
    # Create Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Setup conversation handler for registration
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SECRET_CODE_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, secret_code_input)
            ],
            USERNAME_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, username_input)
            ],
            PROFILE_LINK_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_link_input)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_registration)],
    )
    
    # Add handlers
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("plans", plans_command))
    application.add_handler(CommandHandler("contact", contact_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("mystats", my_stats_command))
    application.add_handler(CommandHandler("myplan", my_plan_command))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    
    # Setup specialized handlers
    setup_admin_handlers(application)
    setup_ticket_handlers(application)
    setup_tools_handlers(application)
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Setup post initialization
    application.post_init = post_init
    
    # Setup scheduled jobs
    job_queue = application.job_queue
    if job_queue:
        # Check subscription expiry daily at 9 AM
        job_queue.run_daily(
            check_subscription_expiry,
            time=datetime.strptime("09:00", "%H:%M").time(),
            days=(0, 1, 2, 3, 4, 5, 6)
        )
        
        # Database health check every hour
        job_queue.run_repeating(
            lambda context: logger.info("Database health: " + ("OK" if db.health_check() else "FAILED")),
            interval=3600,
            first=10
        )
    
    # Start the bot
    logger.info("Starting TheFilex Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()