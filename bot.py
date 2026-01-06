import os
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# Import our modules
import database as db
import tools
from admin_handlers import AdminHandlers, is_admin
from tickets import ticket_system

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from environment
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Initialize handlers
admin_handlers = AdminHandlers()

# Conversation states
WAITING_FOR_DETAILS, WAITING_FOR_PAYMENT, WAITING_FOR_FILES = range(3)

# ==================== HELPER FUNCTIONS ====================
def format_size(bytes_size):
    """Format bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"

def create_main_menu():
    """Create main menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("📤 Upload Files", callback_data="upload_menu")],
        [InlineKeyboardButton("📁 My Files", callback_data="my_files")],
        [InlineKeyboardButton("📤 Send Files", callback_data="send_menu")],
        [InlineKeyboardButton("🎥 YouTube Tools", callback_data="youtube_menu")],
        [InlineKeyboardButton("💰 Plans & Payment", callback_data="payment_menu")],
        [InlineKeyboardButton("📊 My Stats", callback_data="my_stats")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_upload_menu():
    """Create upload menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("📄 Documents", callback_data="upload_docs")],
        [InlineKeyboardButton("🖼️ Images", callback_data="upload_images")],
        [InlineKeyboardButton("🎬 Videos", callback_data="upload_videos")],
        [InlineKeyboardButton("🎵 Audio", callback_data="upload_audio")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_youtube_menu():
    """Create YouTube menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("⬇️ Download Video", callback_data="youtube_download_menu")],
        [InlineKeyboardButton("🎵 Audio Only", callback_data="youtube_audio_menu")],
        [InlineKeyboardButton("📊 Extract Slides", callback_data="youtube_slides_menu")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_payment_menu():
    """Create payment menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("💰 View Plans", callback_data="view_plans")],
        [InlineKeyboardButton("🎫 Create Ticket", callback_data="create_ticket")],
        [InlineKeyboardButton("📱 Pay via QR", callback_data="pay_qr")],
        [InlineKeyboardButton("🎁 Redeem Code", callback_data="redeem_code_menu")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== START COMMAND ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user = update.effective_user
    
    # Check if user is admin
    if is_admin(user.id):
        await admin_handlers.admin_panel(update, context)
        return
    
    # Create user in database
    user_id = db.create_user(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name,
        profile_link=f"https://t.me/{user.username}" if user.username else ""
    )
    
    if user_id:
        # Check if user is approved
        user_data = db.get_user(user.id)
        if user_data and user_data[5]:  # approved column
            # User is approved, show main menu
            await update.message.reply_text(
                "🤖 **Welcome back to Secure File Storage Bot!**\n\n"
                "What would you like to do today?",
                reply_markup=create_main_menu()
            )
        else:
            # User not approved yet
            await update.message.reply_text(
                "👋 **Welcome!**\n\n"
                "Please send your Telegram details for approval:\n\n"
                "**Format:**\n"
                "@username\n"
                "https://t.me/username\n\n"
                "**Example:**\n"
                "@john_doe\n"
                "https://t.me/john_doe\n\n"
                "Send both lines together."
            )
            return WAITING_FOR_DETAILS
    else:
        await update.message.reply_text(
            "❌ Error creating your account. Please try again."
        )

async def handle_user_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user registration details"""
    user = update.effective_user
    text = update.message.text.strip()
    
    if not text:
        await update.message.reply_text("Please send your details in the requested format.")
        return WAITING_FOR_DETAILS
    
    lines = text.split('\n')
    if len(lines) < 2:
        await update.message.reply_text("Please send both username and profile link.")
        return WAITING_FOR_DETAILS
    
    username = lines[0].strip()
    profile_link = lines[1].strip()
    
    # Validate username
    if not username.startswith('@'):
        await update.message.reply_text("Username should start with @ (e.g., @username)")
        return WAITING_FOR_DETAILS
    
    # Update user in database
    success = db.approve_user(user.id)
    
    if success:
        await update.message.reply_text(
            "✅ **Details submitted successfully!**\n\n"
            "Your account is pending admin approval.\n"
            "You'll be notified once approved.\n\n"
            "Meanwhile, you can view subscription plans.",
            reply_markup=create_main_menu()
        )
        
        db.log_activity(
            user_id=user.id,
            activity_type='registration',
            activity_details=f'Submitted details: {username}'
        )
        
        # Notify admin (in real implementation)
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Error saving details. Please try again.")
        return WAITING_FOR_DETAILS

# ==================== FILE UPLOAD COMMANDS ====================
async def upload_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document upload"""
    user = update.effective_user
    
    # Check subscription
    subscription = db.check_subscription(user.id)
    if not subscription:
        await update.message.reply_text(
            "❌ **Subscription Required**\n\n"
            "You need an active subscription to upload files.\n"
            "Use /plans to view available plans."
        )
        return
    
    await update.message.reply_text(
        "📤 **Upload Documents**\n\n"
        "Please send your document files (PDF, DOC, PPT, etc.).\n"
        "Maximum file size: 2GB\n\n"
        "Send /cancel to stop uploading."
    )
    
    return WAITING_FOR_FILES

async def upload_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle image upload"""
    user = update.effective_user
    
    subscription = db.check_subscription(user.id)
    if not subscription:
        await update.message.reply_text(
            "❌ **Subscription Required**\n\n"
            "You need an active subscription to upload files.\n"
            "Use /plans to view available plans."
        )
        return
    
    await update.message.reply_text(
        "🖼️ **Upload Images**\n\n"
        "Please send your image files (JPG, PNG, GIF, etc.).\n"
        "Maximum file size: 2GB\n\n"
        "Send /cancel to stop uploading."
    )
    
    return WAITING_FOR_FILES

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded files"""
    user = update.effective_user
    
    # Check what type of file was sent
    if update.message.document:
        file = update.message.document
        file_type = 'document'
    elif update.message.photo:
        file = update.message.photo[-1]  # Get largest photo
        file_type = 'image'
    elif update.message.video:
        file = update.message.video
        file_type = 'video'
    elif update.message.audio:
        file = update.message.audio
        file_type = 'audio'
    else:
        await update.message.reply_text("❌ Unsupported file type.")
        return WAITING_FOR_FILES
    
    try:
        # Get file info
        file_name = file.file_name if hasattr(file, 'file_name') else f"{file_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        file_size = file.file_size
        
        # Check file size (2GB limit)
        if file_size > 2 * 1024 * 1024 * 1024:  # 2GB in bytes
            await update.message.reply_text("❌ File too large. Maximum size is 2GB.")
            return WAITING_FOR_FILES
        
        # Get file data
        file_obj = await file.get_file()
        file_data = await file_obj.download_as_bytearray()
        
        # Add to database
        file_id = db.add_file(
            user_id=user.id,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            encrypted_data=bytes(file_data)  # Store encrypted in production
        )
        
        if file_id:
            await update.message.reply_text(
                f"✅ **File uploaded successfully!**\n\n"
                f"**Filename:** {file_name}\n"
                f"**Size:** {format_size(file_size)}\n"
                f"**Type:** {file_type}\n\n"
                f"Send another file or /cancel to stop."
            )
            
            db.log_activity(
                user_id=user.id,
                activity_type='file_upload',
                activity_details=f'Uploaded {file_name} ({format_size(file_size)})'
            )
        else:
            await update.message.reply_text("❌ Failed to save file. Please try again.")
    
    except Exception as e:
        logger.error(f"File upload error: {e}")
        await update.message.reply_text("❌ Error uploading file. Please try again.")
    
    return WAITING_FOR_FILES

# ==================== FILE MANAGEMENT ====================
async def my_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's files"""
    user = update.effective_user
    
    subscription = db.check_subscription(user.id)
    if not subscription:
        await update.message.reply_text(
            "❌ **Subscription Required**\n\n"
            "You need an active subscription to view files.\n"
            "Use /plans to view available plans."
        )
        return
    
    files = db.get_user_files(user.id, limit=10)
    
    if not files:
        await update.message.reply_text(
            "📭 **No Files Found**\n\n"
            "You haven't uploaded any files yet.\n"
            "Use the upload menu to add files."
        )
        return
    
    text = "📁 **Your Recent Files:**\n\n"
    total_size = 0
    
    for file in files:
        file_name = file[2]
        file_type = file[3]
        file_size = file[4]
        upload_date = file[7]
        
        total_size += file_size
        
        if isinstance(upload_date, datetime):
            upload_date = upload_date.strftime('%d/%m %H:%M')
        
        size_formatted = format_size(file_size)
        text += f"• {file_name}\n  📦 {file_type} | 📏 {size_formatted} | 🕒 {upload_date}\n"
    
    text += f"\n📊 **Total:** {len(files)} files, {format_size(total_size)}"
    
    # Create keyboard for file actions
    keyboard = [
        [InlineKeyboardButton("📄 Documents", callback_data="my_docs")],
        [InlineKeyboardButton("🖼️ Images", callback_data="my_images")],
        [InlineKeyboardButton("🎬 Videos", callback_data="my_videos")],
        [InlineKeyboardButton("🎵 Audio", callback_data="my_audio")],
        [InlineKeyboardButton("🔍 Search Files", callback_data="search_files")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Check if it's a callback query or message
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

# ==================== YOUTUBE TOOLS ====================
async def youtube_download_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """YouTube download menu"""
    user = update.effective_user
    
    subscription = db.check_subscription(user.id)
    if not subscription:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "❌ **Subscription Required**\n\n"
                "You need an active subscription to use YouTube tools.\n"
                "Use /plans to view available plans."
            )
        return
    
    keyboard = [
        [InlineKeyboardButton("144p", callback_data="yt_144")],
        [InlineKeyboardButton("240p", callback_data="yt_240")],
        [InlineKeyboardButton("360p", callback_data="yt_360")],
        [InlineKeyboardButton("480p", callback_data="yt_480")],
        [InlineKeyboardButton("720p (HD)", callback_data="yt_720")],
        [InlineKeyboardButton("1080p (Full HD)", callback_data="yt_1080")],
        [InlineKeyboardButton("🔙 Back", callback_data="youtube_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🎬 **YouTube Video Download**\n\n"
        "Select video quality:\n\n"
        "After selecting quality, send YouTube URL in format:\n"
        "`https://youtube.com/watch?v=VIDEO_ID`\n\n"
        "Or simply send the YouTube link.",
        reply_markup=reply_markup
    )

async def handle_youtube_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle YouTube download request"""
    user = update.effective_user
    
    # Check if user has selected quality
    quality = context.user_data.get('youtube_quality', '720p')
    
    url = update.message.text.strip()
    
    if not url or 'youtube.com' not in url and 'youtu.be' not in url:
        await update.message.reply_text(
            "❌ Please send a valid YouTube URL.\n"
            "Example: https://youtube.com/watch?v=VIDEO_ID"
        )
        return
    
    try:
        # Show downloading message
        status_msg = await update.message.reply_text("⏳ Downloading video...")
        
        # Download video
        video_path, title = await tools.YouTubeDownloader.download_video(url, quality)
        
        if video_path and title:
            # Send video
            await update.message.reply_video(
                video=open(video_path, 'rb'),
                caption=f"🎬 **{title}**\n\nQuality: {quality}"
            )
            
            # Delete status message
            await status_msg.delete()
            
            # Cleanup temporary file
            try:
                os.unlink(video_path)
            except:
                pass
            
            db.log_activity(
                user_id=user.id,
                activity_type='youtube_download',
                activity_details=f'Downloaded: {title[:50]}...'
            )
        else:
            await status_msg.edit_text(f"❌ Failed to download video: {title}")
    
    except Exception as e:
        logger.error(f"YouTube download error: {e}")
        await update.message.reply_text(f"❌ Error downloading video: {str(e)}")

# ==================== PAYMENT & PLANS ====================
async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show subscription plans"""
    text = """
💰 **SUBSCRIPTION PLANS:**

📅 **Monthly:** ₹25
• 30 days validity
• 5GB storage
• Basic support

📅 **Quarterly:** ₹60 (Save ₹15)
• 90 days validity  
• 15GB storage
• Priority support

📅 **Half-Yearly:** ₹125 (Save ₹25)
• 180 days validity
• 30GB storage
• Priority support

📅 **Yearly:** ₹275 (Save ₹25)
• 365 days validity
• 100GB storage
• Premium support
• Early access to features

🎫 **How to Subscribe:**
1. Use /ticket to create payment request
2. Pay via UPI/QR/Bank Transfer
3. Share payment proof with admin
4. Get activated within 24 hours

📱 **Quick Payment:**
• UPI: `7960003520@ybl`
• Use /pay_via_qr for QR code
"""
    
    keyboard = [
        [InlineKeyboardButton("🎫 Create Ticket", callback_data="create_ticket")],
        [InlineKeyboardButton("📱 Pay via QR", callback_data="pay_qr")],
        [InlineKeyboardButton("🎁 Redeem Code", callback_data="redeem_code")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def pay_via_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate QR code for payment"""
    try:
        # Get QR code
        qr_code = tools.QRCodeGenerator.generate_upi_qr(
            upi_id="7960003520@ybl",
            amount=None,  # Let user enter amount
            name="File Storage Bot"
        )
        
        if qr_code:
            await update.message.reply_photo(
                photo=qr_code,
                caption="📱 **Scan QR to Pay**\n\n"
                       "**UPI ID:** `7960003520@ybl`\n\n"
                       "**Instructions:**\n"
                       "1. Open any UPI app\n"
                       "2. Scan QR code\n"
                       "3. Enter amount as per your plan\n"
                       "4. Make payment\n"
                       "5. Create ticket with screenshot\n\n"
                       "Use /ticket to create payment request."
            )
        else:
            await update.message.reply_text(
                "❌ Failed to generate QR code.\n"
                "Please use UPI ID: `7960003520@ybl`"
            )
    
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        await update.message.reply_text(
            "❌ Error generating QR code.\n"
            "Please use UPI ID: `7960003520@ybl`"
        )

async def redeem_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redeem a code"""
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "🎁 **Redeem Code**\n\n"
            "Usage: /redeem CODE\n\n"
            "Example: /redeem RC123ABC\n\n"
            "Get codes from admin for discounts."
        )
        return
    
    code = args[0].strip().upper()
    user = update.effective_user
    
    # Validate code
    code_info, message = db.validate_redeem_code(code, user.id)
    
    if code_info:
        plan_type = code_info['plan_type']
        value = code_info['value']
        
        # Plan configurations
        plans = {
            'monthly': {'price': 25, 'days': 30},
            'quarterly': {'price': 60, 'days': 90},
            'half_yearly': {'price': 125, 'days': 180},
            'yearly': {'price': 275, 'days': 365}
        }
        
        if plan_type in plans:
            days = plans[plan_type]['days']
            
            # Add subscription
            success = db.add_subscription(
                user_id=user.id,
                plan_type=plan_type,
                price=value,
                days=days,
                payment_method='redeem_code',
                transaction_id=f"redeem_{code}"
            )
            
            if success:
                await update.message.reply_text(
                    f"🎉 **Redeem Successful!**\n\n"
                    f"**Code:** {code}\n"
                    f"**Plan:** {plan_type.capitalize()}\n"
                    f"**Value:** ₹{value}\n"
                    f"**Validity:** {days} days\n\n"
                    f"Your subscription has been activated!"
                )
                
                db.log_activity(
                    user_id=user.id,
                    activity_type='redeem_code',
                    activity_details=f'Redeemed code {code} for {plan_type} plan'
                )
            else:
                await update.message.reply_text(
                    "❌ Failed to activate subscription.\n"
                    "Please contact admin."
                )
        else:
            await update.message.reply_text("❌ Invalid plan type in code.")
    else:
        await update.message.reply_text(f"❌ {message}")

# ==================== STATISTICS ====================
async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics"""
    user = update.effective_user
    
    # Get user stats
    stats = db.get_user_stats(user.id)
    subscription = db.get_user_subscription(user.id)
    
    text = "📊 **Your Statistics**\n\n"
    
    if subscription:
        plan_type = subscription[2]
        expiry = subscription[5]
        storage_limit = subscription[3]
        
        if isinstance(expiry, datetime):
            expiry_str = expiry.strftime('%d %b %Y')
            days_left = (expiry - datetime.now()).days
            
            text += f"📅 **Plan:** {plan_type.capitalize()}\n"
            text += f"📅 **Expiry:** {expiry_str}\n"
            text += f"⏰ **Days Left:** {days_left}\n\n"
    else:
        text += "📅 **Plan:** No active subscription\n\n"
    
    text += f"📁 **Total Files:** {stats['total_files']}\n"
    text += f"📦 **Storage Used:** {format_size(stats['storage_used'])}\n"
    
    if subscription:
        storage_limit = subscription[3]
        if storage_limit > 0:
            percentage = (stats['storage_used'] / storage_limit) * 100
            text += f"📊 **Storage Limit:** {format_size(storage_limit)}\n"
            text += f"📈 **Usage:** {percentage:.1f}%\n\n"
    
    # Show file type breakdown
    if stats['file_types']:
        text += "**Files by Type:**\n"
        for file_type, count, size in stats['file_types']:
            text += f"• {file_type}: {count} files ({format_size(size)})\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

# ==================== HELP COMMAND ====================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help information"""
    text = """
🤖 **BOT COMMANDS GUIDE**

📁 **File Management:**
• /upload_docs - Upload documents
• /upload_images - Upload images  
• /upload_videos - Upload videos
• /upload_audio - Upload audio
• /myfiles - View your files

🎥 **YouTube Tools:**
• /youtube_download URL - Download video
• /youtube_audio URL - Download audio only
• /youtube_slides URL - Extract slides

💰 **Payment & Plans:**
• /plans - View subscription plans
• /ticket - Create payment ticket
• /pay_via_qr - Get QR code for payment
• /redeem CODE - Redeem payment code

📊 **Account:**
• /mystats - Storage statistics
• /myplan - Subscription details

❓ **Support:**
• /help - This message
• /contact - Contact admin

🔐 **Admin Commands:**
• /admin_code 2008 - Setup admin access
• /adduser @username plan - Add user
• /viewstorage @username - View user files
• /download @username filename - Download user file

**Need Help?**
Create a ticket using /ticket or contact admin directly.
"""
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

# ==================== CALLBACK QUERY HANDLER ====================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "main_menu":
        await query.edit_message_text(
            "🤖 **Main Menu**\n\n"
            "Select an option:",
            reply_markup=create_main_menu()
        )
    
    elif data == "upload_menu":
        await query.edit_message_text(
            "📤 **Upload Files**\n\n"
            "Select file type to upload:",
            reply_markup=create_upload_menu()
        )
    
    elif data in ["upload_docs", "upload_images", "upload_videos", "upload_audio"]:
        file_type = data.replace("upload_", "")
        if file_type == "docs":
            await upload_docs(query, context)
        elif file_type == "images":
            await upload_images(query, context)
        # Add other file types...
    
    elif data == "my_files":
        await my_files(update, context)
    
    elif data == "youtube_menu":
        await query.edit_message_text(
            "🎥 **YouTube Tools**\n\n"
            "Select an option:",
            reply_markup=create_youtube_menu()
        )
    
    elif data == "youtube_download_menu":
        await youtube_download_menu(update, context)
    
    elif data.startswith("yt_"):
        quality = data.replace("yt_", "")
        context.user_data['youtube_quality'] = quality
        await query.edit_message_text(
            f"🎬 **Selected Quality: {quality}p**\n\n"
            "Now send the YouTube URL:\n"
            "Example: https://youtube.com/watch?v=VIDEO_ID"
        )
    
    elif data == "payment_menu":
        await query.edit_message_text(
            "💰 **Payment & Plans**\n\n"
            "Select an option:",
            reply_markup=create_payment_menu()
        )
    
    elif data == "view_plans":
        await plans(update, context)
    
    elif data == "create_ticket":
        await ticket_system.create_payment_ticket(update, context)
    
    elif data == "pay_qr":
        await pay_via_qr(update, context)
    
    elif data == "redeem_code_menu":
        await query.edit_message_text(
            "🎁 **Redeem Code**\n\n"
            "Use command: /redeem CODE\n\n"
            "Example: /redeem RC123ABC\n\n"
            "Get codes from admin for discounts."
        )
    
    elif data == "my_stats":
        await my_stats(update, context)
    
    elif data == "help":
        await help_command(update, context)
    
    # Admin callbacks
    elif data.startswith("admin_"):
        await admin_handlers.admin_callback_handler(update, context)

# ==================== CANCEL COMMAND ====================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    await update.message.reply_text(
        "Operation cancelled.\n"
        "Use /start to return to main menu."
    )
    return ConversationHandler.END

# ==================== ERROR HANDLER ====================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        await update.message.reply_text(
            "❌ An error occurred. Please try again later."
        )
    except:
        pass

# ==================== MAIN FUNCTION ====================
def main():
    """Start the bot"""
    # Initialize database
    db.init_db()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Create conversation handler for user registration
    registration_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            WAITING_FOR_DETAILS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_details)
            ],
            WAITING_FOR_FILES: [
                MessageHandler(
                    filters.DOCUMENT | filters.PHOTO | filters.VIDEO | filters.AUDIO,
                    handle_file_upload
                ),
                CommandHandler('cancel', cancel)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    
    # Add handlers
    application.add_handler(registration_handler)
    
    # User commands
    application.add_handler(CommandHandler("plans", plans))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("mystats", my_stats))
    application.add_handler(CommandHandler("myfiles", my_files))
    application.add_handler(CommandHandler("pay_via_qr", pay_via_qr))
    application.add_handler(CommandHandler("redeem", redeem_code))
    
    # File upload commands
    application.add_handler(CommandHandler("upload_docs", upload_docs))
    application.add_handler(CommandHandler("upload_images", upload_images))
    
    # YouTube commands
    application.add_handler(CommandHandler("youtube_download", handle_youtube_download))
    
    # Admin commands
    application.add_handler(CommandHandler("admin_code", admin_handlers.admin_code_command))
    application.add_handler(CommandHandler("admin", admin_handlers.admin_panel))
    application.add_handler(CommandHandler("adduser", admin_handlers.add_user_command))
    application.add_handler(CommandHandler("approve", admin_handlers.approve_user_command))
    application.add_handler(CommandHandler("viewusers", admin_handlers.view_users_command))
    application.add_handler(CommandHandler("userinfo", admin_handlers.view_user_details))
    application.add_handler(CommandHandler("sendmsg", admin_handlers.send_user_message))
    application.add_handler(CommandHandler("gencode", admin_handlers.create_redeem_code))
    application.add_handler(CommandHandler("viewcodes", admin_handlers.view_redeem_codes))
    application.add_handler(CommandHandler("deactivatecode", admin_handlers.deactivate_redeem_code))
    application.add_handler(CommandHandler("viewstorage", admin_handlers.view_storage_command))
    application.add_handler(CommandHandler("download", admin_handlers.download_user_file))
    application.add_handler(CommandHandler("update_qr", admin_handlers.update_qr_command))
    application.add_handler(CommandHandler("broadcast", admin_handlers.broadcast_command))
    application.add_handler(CommandHandler("confirm_broadcast", admin_handlers.confirm_broadcast))
    
    # Ticket commands
    application.add_handler(CommandHandler("ticket", ticket_system.create_payment_ticket))
    application.add_handler(CommandHandler("ticket_status", ticket_system.view_ticket_status))
    application.add_handler(CommandHandler("close_ticket", ticket_system.close_ticket))
    application.add_handler(CommandHandler("support", ticket_system.create_support_ticket))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # Ticket callback handler
    application.add_handler(CallbackQueryHandler(ticket_system.handle_ticket_callback, pattern="^(payment_methods_|contact_admin_|close_ticket_|payment_)"))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("Starting bot...")
    application.run_polling()

if __name__ == '__main__':
    main()