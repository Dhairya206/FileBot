import os
import logging
import asyncio
import tempfile
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
import io

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ChatAction, ParseMode
from cryptography.fernet import Fernet
from database import Database

# For YouTube downloads
try:
    from pytube import YouTube
    from pytube.exceptions import PytubeError
    YOUTUBE_AVAILABLE = True
except ImportError:
    YOUTUBE_AVAILABLE = False
    logging.warning("pytube not installed. YouTube features disabled.")

# For PDF creation
try:
    from PIL import Image
    from reportlab.lib.pagesizes import letter, A4, A3, A2, legal
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logging.warning("PIL or reportlab not installed. PDF features disabled.")

logger = logging.getLogger(__name__)
db = Database()

# Encryption setup
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if ENCRYPTION_KEY:
    cipher = Fernet(ENCRYPTION_KEY.encode())
else:
    # Generate a key if not set (for development only)
    key = Fernet.generate_key()
    cipher = Fernet(key)
    logger.warning("Using auto-generated encryption key. Set ENCRYPTION_KEY in production!")

# File type configurations
ALLOWED_MIME_TYPES = {
    'document': [
        'application/pdf', 'application/msword', 
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'text/plain', 'text/csv', 'application/json', 'application/xml'
    ],
    'image': [
        'image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/webp', 'image/tiff'
    ],
    'video': [
        'video/mp4', 'video/mpeg', 'video/quicktime', 'video/x-msvideo', 'video/x-matroska',
        'video/webm', 'video/3gpp'
    ],
    'audio': [
        'audio/mpeg', 'audio/mp4', 'audio/ogg', 'audio/wav', 'audio/webm', 'audio/x-wav',
        'audio/x-m4a', 'audio/flac'
    ]
}

MAX_FILE_SIZES = {
    'document': 100 * 1024 * 1024,  # 100MB
    'image': 20 * 1024 * 1024,      # 20MB
    'video': 500 * 1024 * 1024,     # 500MB
    'audio': 50 * 1024 * 1024       # 50MB
}

# YouTube quality options
YOUTUBE_QUALITIES = ['144p', '240p', '360p', '480p', '720p', '1080p', '1440p', '2160p']

# ==================== FILE UPLOAD HANDLERS ====================

async def upload_docs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /upload_docs command"""
    await start_file_upload(update, context, 'document')

async def upload_images_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /upload_images command"""
    await start_file_upload(update, context, 'image')

async def upload_videos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /upload_videos command"""
    await start_file_upload(update, context, 'video')

async def upload_audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /upload_audio command"""
    await start_file_upload(update, context, 'audio')

async def start_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, file_type: str):
    """Start file upload process"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data or not user_data['subscription_active']:
        await update.message.reply_text(
            "❌ **Subscription Required**\n\n"
            "You need an active subscription to upload files.\n"
            "Use /plans to view available plans.",
            parse_mode='Markdown'
        )
        return
    
    # Check storage limit
    if user_data['storage_used'] >= user_data['storage_limit']:
        await update.message.reply_text(
            "❌ **Storage Limit Reached**\n\n"
            "You have reached your storage limit.\n"
            "Please delete some files or upgrade your plan.",
            parse_mode='Markdown'
        )
        return
    
    context.user_data['upload_type'] = file_type
    context.user_data['upload_state'] = 'waiting'
    
    max_size_mb = MAX_FILE_SIZES[file_type] / (1024 * 1024)
    
    await update.message.reply_text(
        f"📤 **Upload {file_type.title()}**\n\n"
        f"Please send your {file_type} file.\n"
        f"Maximum size: {max_size_mb:.0f}MB\n"
        f"Allowed types: {', '.join([mime.split('/')[1] for mime in ALLOWED_MIME_TYPES[file_type][:3]])}...\n\n"
        f"To cancel, send /cancel",
        parse_mode='Markdown'
    )

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming file uploads"""
    user_id = update.effective_user.id
    
    # Check if user is in upload mode
    if 'upload_state' not in context.user_data or context.user_data['upload_state'] != 'waiting':
        return
    
    file_type = context.user_data.get('upload_type')
    if not file_type:
        return
    
    # Get user data
    user_data = db.get_user(user_id)
    if not user_data or not user_data['subscription_active']:
        await update.message.reply_text("❌ No active subscription.")
        context.user_data.clear()
        return
    
    # Check available storage
    available_storage = user_data['storage_limit'] - user_data['storage_used']
    if available_storage <= 0:
        await update.message.reply_text("❌ Storage limit reached.")
        context.user_data.clear()
        return
    
    # Get file from message
    file = None
    filename = ""
    mime_type = ""
    file_size = 0
    
    if file_type == 'document' and update.message.document:
        file = update.message.document
        filename = file.file_name or "document"
        mime_type = file.mime_type or 'application/octet-stream'
    elif file_type == 'image' and update.message.photo:
        # Get the highest quality photo
        file = update.message.photo[-1]
        filename = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        mime_type = 'image/jpeg'
    elif file_type == 'video' and update.message.video:
        file = update.message.video
        filename = file.file_name or f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        mime_type = file.mime_type or 'video/mp4'
    elif file_type == 'audio' and update.message.audio:
        file = update.message.audio
        filename = file.file_name or f"audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        mime_type = file.mime_type or 'audio/mpeg'
    else:
        await update.message.reply_text(f"❌ Please send a {file_type} file.")
        return
    
    if not file:
        await update.message.reply_text(f"❌ Invalid file type for {file_type} upload.")
        return
    
    file_size = file.file_size
    telegram_file_id = file.file_id
    
    # Validate file size
    max_size = MAX_FILE_SIZES[file_type]
    if file_size > max_size:
        await update.message.reply_text(
            f"❌ File too large. Maximum size for {file_type}s is {max_size/(1024*1024):.0f}MB."
        )
        context.user_data.clear()
        return
    
    if file_size > available_storage:
        await update.message.reply_text(
            f"❌ Not enough storage. Available: {available_storage/(1024*1024):.1f}MB, "
            f"File size: {file_size/(1024*1024):.1f}MB"
        )
        context.user_data.clear()
        return
    
    # Validate MIME type
    allowed_types = ALLOWED_MIME_TYPES[file_type]
    if mime_type not in allowed_types:
        await update.message.reply_text(
            f"❌ File type not allowed for {file_type}s.\n"
            f"Allowed: {', '.join([mime.split('/')[1] for mime in allowed_types[:3]])}..."
        )
        context.user_data.clear()
        return
    
    # Show processing message
    processing_msg = await update.message.reply_text(
        f"⏳ Processing {filename} ({file_size/(1024*1024):.1f}MB)..."
    )
    
    try:
        # Generate encryption key for this file
        file_key = Fernet.generate_key()
        file_cipher = Fernet(file_key)
        
        # Encrypt the file key with master key
        encrypted_key = cipher.encrypt(file_key)
        
        # Save file to database
        file_id = db.add_file(
            user_id=user_data['id'],
            telegram_file_id=telegram_file_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            mime_type=mime_type,
            encryption_key=encrypted_key.decode('utf-8')
        )
        
        if file_id:
            # Update context
            context.user_data.clear()
            
            # Delete processing message
            try:
                await processing_msg.delete()
            except:
                pass
            
            await update.message.reply_text(
                f"✅ **File Uploaded Successfully**\n\n"
                f"📁 Filename: `{filename}`\n"
                f"📦 Size: {file_size/(1024*1024):.1f}MB\n"
                f"🔐 Encrypted: Yes\n"
                f"📅 Uploaded: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"🆔 File ID: `{file_id}`\n\n"
                f"Storage used: {user_data['storage_used'] + file_size}/{user_data['storage_limit']} bytes",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Failed to save file to database.")
    
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        await update.message.reply_text(f"❌ Error uploading file: {str(e)}")
        context.user_data.clear()

# ==================== FILE VIEWING COMMANDS ====================

async def my_files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /myfiles command - show all files"""
    await show_user_files(update, context, file_type=None)

async def my_docs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mydocs command - show documents"""
    await show_user_files(update, context, file_type='document')

async def my_images_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /myimages command - show images"""
    await show_user_files(update, context, file_type='image')

async def show_user_files(update: Update, context: ContextTypes.DEFAULT_TYPE, file_type: Optional[str] = None):
    """Show user's files"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data or not user_data['subscription_active']:
        await update.message.reply_text("❌ No active subscription.")
        return
    
    # Get files from database
    files = db.get_user_files(user_data['id'], file_type=file_type, limit=20)
    
    if not files:
        type_text = file_type + "s" if file_type else "files"
        await update.message.reply_text(f"📭 You don't have any {type_text}.")
        return
    
    # Create response
    if file_type:
        title = f"Your {file_type.title()}s"
    else:
        title = "Your Files"
    
    response = f"📁 **{title}**\n\n"
    
    for i, file in enumerate(files, 1):
        size_mb = file['file_size'] / (1024 * 1024)
        response += (
            f"{i}. **{file['filename']}**\n"
            f"   📦 {size_mb:.1f}MB | 📅 {file['uploaded_at'].strftime('%Y-%m-%d')}\n"
            f"   🆔 `{file['id']}` | 🔗 `/getfile_{file['id']}`\n\n"
        )
    
    # Add pagination if needed
    if len(files) == 20:
        response += "📄 *Showing 20 most recent files*\n"
    
    await update.message.reply_text(response, parse_mode='Markdown')

async def send_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file sending commands"""
    command = update.message.text.lower()
    
    if 'send_docs' in command:
        file_type = 'document'
    elif 'send_images' in command:
        file_type = 'image'
    else:
        await update.message.reply_text("Invalid command.")
        return
    
    await update.message.reply_text(
        f"To send {file_type}s, please use:\n"
        f"1. First, find the file ID using /my{file_type}s\n"
        f"2. Then use: /sendfile file_id @username\n\n"
        f"Example: `/sendfile 123 @username`",
        parse_mode='Markdown'
    )

# ==================== YOUTUBE TOOLS ====================

async def youtube_download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /youtube_download command"""
    if not YOUTUBE_AVAILABLE:
        await update.message.reply_text("❌ YouTube features are not available.")
        return
    
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data or not user_data['subscription_active']:
        await update.message.reply_text("❌ No active subscription.")
        return
    
    # Check if URL provided
    if context.args:
        url = ' '.join(context.args)
        await process_youtube_download(update, context, url)
    else:
        # Ask for URL
        context.user_data['youtube_action'] = 'download'
        await update.message.reply_text(
            "🎥 **YouTube Video Download**\n\n"
            "Please send the YouTube video URL.\n\n"
            "Supported formats:\n"
            "• Full videos\n"
            "• Playlists (first video only)\n"
            "• Shorts\n\n"
            "To cancel, send /cancel",
            parse_mode='Markdown'
        )

async def youtube_audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /youtube_audio command"""
    if not YOUTUBE_AVAILABLE:
        await update.message.reply_text("❌ YouTube features are not available.")
        return
    
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data or not user_data['subscription_active']:
        await update.message.reply_text("❌ No active subscription.")
        return
    
    # Check if URL provided
    if context.args:
        url = ' '.join(context.args)
        await process_youtube_audio(update, context, url)
    else:
        # Ask for URL
        context.user_data['youtube_action'] = 'audio'
        await update.message.reply_text(
            "🎵 **YouTube Audio Extraction**\n\n"
            "Please send the YouTube video URL to extract audio.\n\n"
            "The audio will be extracted in MP3 format.\n"
            "To cancel, send /cancel",
            parse_mode='Markdown'
        )

async def youtube_slides_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /youtube_slides command"""
    await update.message.reply_text(
        "🖼️ **YouTube Slides Creation**\n\n"
        "This feature creates presentation slides from YouTube videos.\n\n"
        "Coming soon in the next update!\n\n"
        "For now, you can use:\n"
        "• /youtube_download - Download videos\n"
        "• /youtube_audio - Extract audio",
        parse_mode='Markdown'
    )

async def process_youtube_download(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Process YouTube video download"""
    user_id = update.effective_user.id
    
    # Show quality selection
    keyboard = []
    row = []
    for i, quality in enumerate(YOUTUBE_QUALITIES):
        row.append(InlineKeyboardButton(quality, callback_data=f"yt_quality_{quality}"))
        if len(row) == 2 or i == len(YOUTUBE_QUALITIES) - 1:
            keyboard.append(row)
            row = []
    
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="yt_cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Store URL in context
    context.user_data['youtube_url'] = url
    context.user_data['youtube_action'] = 'download'
    
    await update.message.reply_text(
        f"🔗 URL: `{url}`\n\n"
        "Select video quality:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def process_youtube_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Process YouTube audio extraction"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    # Check storage
    if user_data['storage_used'] >= user_data['storage_limit']:
        await update.message.reply_text("❌ Storage limit reached.")
        return
    
    processing_msg = await update.message.reply_text("⏳ Extracting audio from YouTube...")
    
    try:
        # Download YouTube video
        yt = YouTube(url)
        
        # Get audio stream
        audio_stream = yt.streams.filter(only_audio=True).first()
        
        if not audio_stream:
            await update.message.reply_text("❌ No audio stream found.")
            return
        
        # Create temp file
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
            temp_path = tmp_file.name
        
        # Download audio
        audio_stream.download(filename=temp_path)
        
        # Get file size
        file_size = os.path.getsize(temp_path)
        
        # Check if enough storage
        if user_data['storage_used'] + file_size > user_data['storage_limit']:
            await update.message.reply_text("❌ Not enough storage for this file.")
            os.unlink(temp_path)
            return
        
        # Send audio file
        with open(temp_path, 'rb') as audio_file:
            await update.message.reply_audio(
                audio=audio_file,
                title=f"{yt.title}.mp3",
                caption=f"🎵 **{yt.title}**\n\n"
                       f"Duration: {yt.length//60}:{yt.length%60:02d}\n"
                       f"Size: {file_size/(1024*1024):.1f}MB\n"
                       f"From: {url}",
                parse_mode='Markdown'
            )
        
        # Save to database
        file_id = db.add_file(
            user_id=user_data['id'],
            telegram_file_id="youtube_audio",  # Placeholder
            filename=f"{yt.title}.mp3",
            file_type='audio',
            file_size=file_size,
            mime_type='audio/mpeg'
        )
        
        # Record in YouTube downloads
        db.add_youtube_download(
            user_id=user_data['id'],
            video_url=url,
            video_id=yt.video_id,
            title=yt.title,
            quality='audio',
            format_type='audio'
        )
        
        # Cleanup
        os.unlink(temp_path)
        
        await processing_msg.delete()
        
    except Exception as e:
        logger.error(f"YouTube audio error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def youtube_quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle YouTube quality selection"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "yt_cancel":
        await query.edit_message_text("YouTube download cancelled.")
        context.user_data.pop('youtube_url', None)
        context.user_data.pop('youtube_action', None)
        return
    
    if data.startswith("yt_quality_"):
        quality = data.replace("yt_quality_", "")
        url = context.user_data.get('youtube_url')
        action = context.user_data.get('youtube_action')
        
        if not url:
            await query.edit_message_text("❌ No URL found. Please start over.")
            return
        
        await query.edit_message_text(f"⏳ Downloading {quality} video...")
        
        try:
            # Download YouTube video
            yt = YouTube(url)
            
            # Get stream for selected quality
            if quality == 'audio':
                stream = yt.streams.filter(only_audio=True).first()
            else:
                stream = yt.streams.filter(res=quality, progressive=True).first()
                if not stream:
                    stream = yt.streams.filter(res=quality).first()
            
            if not stream:
                await query.edit_message_text(f"❌ {quality} not available for this video.")
                return
            
            # Create temp file
            ext = 'mp4' if quality != 'audio' else 'mp3'
            with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False) as tmp_file:
                temp_path = tmp_file.name
            
            # Download video
            stream.download(filename=temp_path)
            file_size = os.path.getsize(temp_path)
            
            # Send file
            if quality == 'audio':
                with open(temp_path, 'rb') as file:
                    await query.message.reply_audio(
                        audio=file,
                        title=f"{yt.title}.{ext}",
                        caption=f"🎵 {yt.title}"
                    )
            else:
                with open(temp_path, 'rb') as file:
                    await query.message.reply_video(
                        video=file,
                        caption=f"🎥 {yt.title} ({quality})"
                    )
            
            # Record in database
            user_data = db.get_user(user_id)
            if user_data:
                db.add_youtube_download(
                    user_id=user_data['id'],
                    video_url=url,
                    video_id=yt.video_id,
                    title=yt.title,
                    quality=quality,
                    format_type='audio' if quality == 'audio' else 'video'
                )
            
            # Cleanup
            os.unlink(temp_path)
            
            await query.edit_message_text(f"✅ Download complete: {quality}")
            
        except Exception as e:
            logger.error(f"YouTube download error: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")
        
        finally:
            context.user_data.pop('youtube_url', None)
            context.user_data.pop('youtube_action', None)

# ==================== PDF CREATION TOOLS ====================

async def create_pdf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /create_pdf command"""
    if not PDF_AVAILABLE:
        await update.message.reply_text("❌ PDF features are not available.")
        return
    
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data or not user_data['subscription_active']:
        await update.message.reply_text("❌ No active subscription.")
        return
    
    # Check if we're in PDF creation mode
    if 'pdf_creation' in context.user_data:
        await update.message.reply_text(
            "📄 **PDF Creation in Progress**\n\n"
            "Please send images to add to PDF.\n"
            "When done, send /pdf_done\n"
            "To cancel, send /pdf_cancel"
        )
        return
    
    # Start PDF creation
    context.user_data['pdf_creation'] = {
        'images': [],
        'page_size': 'A4',
        'quality': 'medium'
    }
    
    # Show page size selection
    keyboard = [
        [
            InlineKeyboardButton("A4", callback_data="pdf_size_A4"),
            InlineKeyboardButton("Letter", callback_data="pdf_size_letter"),
            InlineKeyboardButton("A3", callback_data="pdf_size_A3")
        ],
        [
            InlineKeyboardButton("High Quality", callback_data="pdf_quality_high"),
            InlineKeyboardButton("Medium Quality", callback_data="pdf_quality_medium"),
            InlineKeyboardButton("Low Quality", callback_data="pdf_quality_low")
        ],
        [
            InlineKeyboardButton("✅ Start Adding Images", callback_data="pdf_start"),
            InlineKeyboardButton("❌ Cancel", callback_data="pdf_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📄 **Create PDF from Images**\n\n"
        "Configure your PDF settings:\n\n"
        "1. **Page Size:** Select paper size\n"
        "2. **Quality:** Select image quality\n"
        "3. **Start:** Begin adding images\n\n"
        "You can add multiple images. Send /pdf_done when finished.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_pdf_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle image addition for PDF creation"""
    if 'pdf_creation' not in context.user_data:
        return
    
    if not update.message.photo:
        await update.message.reply_text("❌ Please send an image.")
        return
    
    # Get the highest quality photo
    photo = update.message.photo[-1]
    
    # Download image
    try:
        processing_msg = await update.message.reply_text("⏳ Processing image...")
        
        # Get file from Telegram
        file = await photo.get_file()
        
        # Create temp file
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
            temp_path = tmp_file.name
        
        # Download image
        await file.download_to_drive(temp_path)
        
        # Add to PDF images
        context.user_data['pdf_creation']['images'].append(temp_path)
        
        count = len(context.user_data['pdf_creation']['images'])
        await processing_msg.delete()
        await update.message.reply_text(
            f"✅ Image {count} added.\n"
            f"Send more images or /pdf_done when finished."
        )
        
    except Exception as e:
        logger.error(f"PDF image error: {e}")
        await update.message.reply_text(f"❌ Error processing image: {str(e)}")

async def complete_pdf_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Complete PDF creation and generate file"""
    if 'pdf_creation' not in context.user_data:
        await update.message.reply_text("No PDF creation in progress.")
        return
    
    pdf_data = context.user_data['pdf_creation']
    images = pdf_data.get('images', [])
    
    if not images:
        await update.message.reply_text("❌ No images added to PDF.")
        context.user_data.pop('pdf_creation', None)
        return
    
    processing_msg = await update.message.reply_text(f"⏳ Creating PDF with {len(images)} images...")
    
    try:
        # Create PDF
        pdf_buffer = create_pdf_from_images(
            images=images,
            page_size=pdf_data.get('page_size', 'A4'),
            quality=pdf_data.get('quality', 'medium')
        )
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"pdf_{timestamp}.pdf"
        
        # Send PDF
        await update.message.reply_document(
            document=pdf_buffer,
            filename=filename,
            caption=f"📄 **PDF Created Successfully**\n\n"
                   f"Images: {len(images)}\n"
                   f"Page Size: {pdf_data.get('page_size', 'A4')}\n"
                   f"Quality: {pdf_data.get('quality', 'medium')}\n"
                   f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        
        # Save to database
        user_id = update.effective_user.id
        user_data = db.get_user(user_id)
        if user_data:
            pdf_buffer.seek(0)
            file_size = len(pdf_buffer.getvalue())
            
            db.add_pdf_creation(
                user_id=user_data['id'],
                filename=filename,
                page_size=pdf_data.get('page_size', 'A4'),
                quality=pdf_data.get('quality', 'medium'),
                file_size=file_size,
                image_count=len(images)
            )
        
        await processing_msg.delete()
        await update.message.reply_text("✅ PDF creation complete!")
        
    except Exception as e:
        logger.error(f"PDF creation error: {e}")
        await update.message.reply_text(f"❌ Error creating PDF: {str(e)}")
    
    finally:
        # Cleanup temp files
        for img_path in images:
            try:
                if os.path.exists(img_path):
                    os.unlink(img_path)
            except:
                pass
        
        # Clear context
        context.user_data.pop('pdf_creation', None)

def create_pdf_from_images(images: List[str], page_size: str = 'A4', quality: str = 'medium') -> io.BytesIO:
    """Create PDF from list of image paths"""
    # Map page sizes
    size_map = {
        'A4': A4,
        'A3': A3,
        'A2': A2,
        'letter': letter,
        'legal': legal
    }
    
    # Map quality to DPI
    quality_map = {
        'high': 300,
        'medium': 150,
        'low': 72
    }
    
    selected_size = size_map.get(page_size, A4)
    dpi = quality_map.get(quality, 150)
    
    # Create PDF in memory
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=selected_size)
    
    width, height = selected_size
    
    for img_path in images:
        try:
            # Open and resize image
            img = Image.open(img_path)
            img_width, img_height = img.size
            
            # Calculate scaling to fit page
            scale_width = width / img_width
            scale_height = height / img_height
            scale = min(scale_width, scale_height) * 0.95  # 5% margin
            
            new_width = img_width * scale
            new_height = img_height * scale
            
            # Center image on page
            x = (width - new_width) / 2
            y = (height - new_height) / 2
            
            # Draw image
            c.drawImage(img_path, x, y, new_width, new_height)
            c.showPage()
            
        except Exception as e:
            logger.error(f"Error adding image to PDF: {e}")
            continue
    
    c.save()
    buffer.seek(0)
    return buffer

async def pdf_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle PDF creation callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("pdf_size_"):
        size = data.replace("pdf_size_", "")
        if 'pdf_creation' in context.user_data:
            context.user_data['pdf_creation']['page_size'] = size
            await query.edit_message_text(f"✅ Page size set to {size}")
    
    elif data.startswith("pdf_quality_"):
        quality = data.replace("pdf_quality_", "")
        if 'pdf_creation' in context.user_data:
            context.user_data['pdf_creation']['quality'] = quality
            await query.edit_message_text(f"✅ Quality set to {quality}")
    
    elif data == "pdf_start":
        await query.edit_message_text(
            "📄 **PDF Creation Started**\n\n"
            "Please send images to add to PDF.\n"
            "When done, send /pdf_done\n"
            "To cancel, send /pdf_cancel"
        )
    
    elif data == "pdf_cancel":
        # Cleanup any temp files
        if 'pdf_creation' in context.user_data:
            for img_path in context.user_data['pdf_creation'].get('images', []):
                try:
                    if os.path.exists(img_path):
                        os.unlink(img_path)
                except:
                    pass
            context.user_data.pop('pdf_creation', None)
        
        await query.edit_message_text("PDF creation cancelled.")

# ==================== UTILITY COMMANDS ====================

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command"""
    # Clear upload state
    if 'upload_state' in context.user_data:
        context.user_data.clear()
        await update.message.reply_text("✅ Upload cancelled.")
    
    # Clear YouTube state
    elif 'youtube_url' in context.user_data:
        context.user_data.clear()
        await update.message.reply_text("✅ YouTube operation cancelled.")
    
    # Clear PDF state
    elif 'pdf_creation' in context.user_data:
        # Cleanup temp files
        for img_path in context.user_data['pdf_creation'].get('images', []):
            try:
                if os.path.exists(img_path):
                    os.unlink(img_path)
            except:
                pass
        context.user_data.pop('pdf_creation', None)
        await update.message.reply_text("✅ PDF creation cancelled.")
    
    else:
        await update.message.reply_text("No active operation to cancel.")

async def pdf_done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pdf_done command"""
    await complete_pdf_creation(update, context)

async def pdf_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pdf_cancel command"""
    await cancel_command(update, context)

# ==================== SETUP FUNCTION ====================

def setup_tools_handlers(application):
    """Setup all tools and file management handlers"""
    
    # File upload commands
    application.add_handler(CommandHandler("upload_docs", upload_docs_command))
    application.add_handler(CommandHandler("upload_images", upload_images_command))
    application.add_handler(CommandHandler("upload_videos", upload_videos_command))
    application.add_handler(CommandHandler("upload_audio", upload_audio_command))
    
    # File viewing commands
    application.add_handler(CommandHandler("myfiles", my_files_command))
    application.add_handler(CommandHandler("mydocs", my_docs_command))
    application.add_handler(CommandHandler("myimages", my_images_command))
    
    # File sending commands
    application.add_handler(CommandHandler("send_docs", send_file_command))
    application.add_handler(CommandHandler("send_images", send_file_command))
    
    # YouTube tools
    application.add_handler(CommandHandler("youtube_download", youtube_download_command))
    application.add_handler(CommandHandler("youtube_audio", youtube_audio_command))
    application.add_handler(CommandHandler("youtube_slides", youtube_slides_command))
    
    # PDF tools
    application.add_handler(CommandHandler("create_pdf", create_pdf_command))
    application.add_handler(CommandHandler("pdf_done", pdf_done_command))
    application.add_handler(CommandHandler("pdf_cancel", pdf_cancel_command))
    
    # Cancel command
    application.add_handler(CommandHandler("cancel", cancel_command))
    
    # File upload handler
    application.add_handler(MessageHandler(
        filters.Document | filters.PHOTO | filters.VIDEO | filters.AUDIO,
        handle_file_upload
    ))
    
    # PDF image handler
    application.add_handler(MessageHandler(
        filters.PHOTO & ~filters.COMMAND,
        handle_pdf_image
    ))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(youtube_quality_callback, pattern="^yt_"))
    application.add_handler(CallbackQueryHandler(pdf_callback_handler, pattern="^pdf_"))
    
    logger.info("Tools handlers setup complete")