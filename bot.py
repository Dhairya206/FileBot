import os
import logging
import psycopg2
from psycopg2 import sql
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from cryptography.fernet import Fernet
import qrcode
from io import BytesIO
from pytube import YouTube
from moviepy.editor import VideoFileClip
from PIL import Image
import tempfile
import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load env vars
BOT_TOKEN = os.getenv('BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = int(os.getenv('ADMIN_ID')) if os.getenv('ADMIN_ID') else None
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if ENCRYPTION_KEY:
    ENCRYPTION_KEY = ENCRYPTION_KEY.encode()
    fernet = Fernet(ENCRYPTION_KEY)
else:
    fernet = None

# Database connection
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# Initialize DB tables
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE,
            username TEXT,
            profile_link TEXT,
            approved BOOLEAN DEFAULT FALSE,
            admin_access BOOLEAN DEFAULT FALSE,
            admin_code_used TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(telegram_id),
            plan TEXT,
            storage_limit BIGINT,
            expiry TIMESTAMP,
            active BOOLEAN DEFAULT TRUE
        );
        CREATE TABLE IF NOT EXISTS files (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(telegram_id),
            filename TEXT,
            file_type TEXT,
            encrypted_data BYTEA,
            size BIGINT,
            uploaded_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS tickets (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(telegram_id),
            group_id BIGINT,
            status TEXT DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS admin_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        INSERT INTO admin_settings (key, value) VALUES ('qr_code_url', 'https://example.com/pay') ON CONFLICT DO NOTHING;
    """)
    conn.commit()
    cursor.close()
    conn.close()

# Admin check
def is_admin(user_id):
    return ADMIN_ID is not None and user_id == ADMIN_ID

# Encrypt/decrypt files
def encrypt_data(data):
    if not fernet:
        raise RuntimeError("Encryption key not set")
    return fernet.encrypt(data)

def decrypt_data(data):
    if not fernet:
        raise RuntimeError("Encryption key not set")
    return fernet.decrypt(data)

# Check subscription
def check_subscription(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT active, expiry FROM subscriptions WHERE user_id = %s AND active = TRUE", (user_id,))
        sub = cursor.fetchone()
        cursor.close()
        conn.close()
        if sub and sub[1] and sub[1] > datetime.now():
            return True
    except Exception:
        return False
    return False

# Background scheduler for expiry
scheduler = AsyncIOScheduler()
application = None  # will be set in main

async def check_expiry():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, expiry FROM subscriptions WHERE active = TRUE AND expiry < NOW() + INTERVAL '1 day'")
        expiring = cursor.fetchall()
        for user_id, expiry in expiring:
            if expiry < datetime.now():
                cursor.execute("UPDATE subscriptions SET active = FALSE WHERE user_id = %s", (user_id,))
            else:
                # Send reminder
                if application:
                    try:
                        await application.bot.send_message(user_id, "Your subscription expires soon. Renew via /ticket.")
                    except Exception:
                        logger.exception("Failed to send expiry reminder to %s", user_id)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        logger.exception("Error in check_expiry")

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (telegram_id, username) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user.id, user.username))
    conn.commit()
    cursor.close()
    conn.close()
    await update.message.reply_text("Welcome! Send your username and profile link for approval. Example: @username https://t.me/username")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    if text and text.startswith('@') and 't.me' in text:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET profile_link = %s WHERE telegram_id = %s", (text, user.id))
        conn.commit()
        cursor.close()
        conn.close()
        await update.message.reply_text("Submitted for approval. Wait for admin confirmation.")

async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    username = context.args[0] if context.args else None
    if not username:
        await update.message.reply_text("Usage: /approve @username")
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET approved = TRUE WHERE username = %s", (username,))
    conn.commit()
    cursor.close()
    conn.close()
    await update.message.reply_text(f"User {username} approved.")

async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
    Subscription Plans:
    - ₹25/month: 5GB
    - ₹60/3 months: 15GB
    - ₹125/6 months: 30GB
    - ₹275/year: 100GB
    Use /ticket to subscribe.
    """
    await update.message.reply_text(text)

async def ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT approved FROM users WHERE telegram_id = %s", (user.id,))
    approved = cursor.fetchone()
    if not approved or not approved[0]:
        await update.message.reply_text("You are not approved yet.")
        return
    # Create private group - note: API may differ; placeholder implementation
    try:
        group = await context.bot.create_chat(title=f"Payment Ticket for {user.username}", user_ids=[user.id])
        group_id = group.id
        invite_link = getattr(group, 'invite_link', 'group-created')
    except Exception:
        # Fallback: use user's id as group reference
        group_id = user.id
        invite_link = 'private'
    cursor.execute("INSERT INTO tickets (user_id, group_id) VALUES (%s, %s)", (user.id, group_id))
    conn.commit()
    cursor.close()
    conn.close()
    await update.message.reply_text(f"Ticket created: {invite_link}. Pay and wait for verification.")

async def pay_via_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM admin_settings WHERE key = 'qr_code_url'")
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    url = row[0] if row else 'https://example.com/pay'
    qr = qrcode.QRCode()
    qr.add_data(url)
    img = qr.make_image()
    bio = BytesIO()
    img.save(bio, format='PNG')
    bio.seek(0)
    await update.message.reply_photo(bio, caption="Scan to pay.")

async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /adduser @username plan (monthly/quarterly/semiannual/yearly)")
        return
    username = args[0]
    plan = args[1]
    plans_dict = {'monthly': (5*1024**3, timedelta(days=30)), 'quarterly': (15*1024**3, timedelta(days=90)), 'semiannual': (30*1024**3, timedelta(days=180)), 'yearly': (100*1024**3, timedelta(days=365))}
    if plan not in plans_dict:
        await update.message.reply_text("Invalid plan.")
        return
    limit, duration = plans_dict[plan]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    if not row:
        await update.message.reply_text("User not found.")
        cursor.close()
        conn.close()
        return
    user_id = row[0]
    expiry = datetime.now() + duration
    cursor.execute("INSERT INTO subscriptions (user_id, plan, storage_limit, expiry) VALUES (%s, %s, %s, %s)", (user_id, plan, limit, expiry))
    conn.commit()
    cursor.close()
    conn.close()
    await update.message.reply_text(f"Subscription added for {username}.")

async def upload_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not check_subscription(user.id):
        await update.message.reply_text("Subscription required.")
        return
    if update.message.document:
        file = await update.message.document.get_file()
        data = await file.download_as_bytearray()
        encrypted = encrypt_data(bytes(data))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO files (user_id, filename, file_type, encrypted_data, size) VALUES (%s, %s, %s, %s, %s)", (user.id, update.message.document.file_name, 'doc', encrypted, len(data)))
        conn.commit()
        cursor.close()
        conn.close()
        await update.message.reply_text("Document uploaded.")

async def upload_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not check_subscription(user.id):
        await update.message.reply_text("Subscription required.")
        return
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        data = await file.download_as_bytearray()
        encrypted = encrypt_data(bytes(data))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO files (user_id, filename, file_type, encrypted_data, size) VALUES (%s, %s, %s, %s, %s)", (user.id, 'image.jpg', 'image', encrypted, len(data)))
        conn.commit()
        cursor.close()
        conn.close()
        await update.message.reply_text("Image uploaded.")

# Similar for /upload_videos and /upload_audio (left as TODO)

async def myfiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT filename, file_type FROM files WHERE user_id = %s", (user.id,))
    files = cursor.fetchall()
    cursor.close()
    conn.close()
    text = "\n".join([f"{f[0]} ({f[1]})" for f in files]) or "No files."
    await update.message.reply_text(text)

async def send_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    filename = " ".join(context.args)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT encrypted_data FROM files WHERE user_id = %s AND filename = %s AND file_type = 'doc'", (user.id, filename))
    data = cursor.fetchone()
    cursor.close()
    conn.close()
    if data:
        decrypted = decrypt_data(data[0])
        bio = BytesIO(decrypted)
        bio.seek(0)
        await update.message.reply_document(bio, filename=filename)
    else:
        await update.message.reply_text("File not found.")

async def youtube_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not check_subscription(user.id):
        await update.message.reply_text("Subscription required.")
        return
    url = context.args[0] if context.args else None
    quality = context.args[1] if len(context.args) > 1 else '720p'
    if not url:
        await update.message.reply_text("Usage: /youtube_download <url> [quality]")
        return
    try:
        yt = YouTube(url)
        stream = yt.streams.filter(res=quality, progressive=True).first()
        if not stream:
            await update.message.reply_text("Quality not available.")
            return
        path = tempfile.mktemp(suffix='.mp4')
        stream.download(output_path=os.path.dirname(path), filename=os.path.basename(path))
        await update.message.reply_video(open(path, 'rb'))
        os.unlink(path)
    except Exception as e:
        logger.exception("youtube_download error")
        await update.message.reply_text(f"Error: {str(e)}")

async def youtube_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not check_subscription(user.id):
        await update.message.reply_text("Subscription required.")
        return
    url = context.args[0] if context.args else None
    if not url:
        await update.message.reply_text("Usage: /youtube_audio <url>")
        return
    try:
        yt = YouTube(url)
        stream = yt.streams.filter(only_audio=True).first()
        path = tempfile.mktemp(suffix='.mp3')
        stream.download(output_path=os.path.dirname(path), filename=os.path.basename(path))
        await update.message.reply_audio(open(path, 'rb'))
        os.unlink(path)
    except Exception as e:
        logger.exception("youtube_audio error")
        await update.message.reply_text(f"Error: {str(e)}")

async def youtube_slides(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not check_subscription(user.id):
        await update.message.reply_text("Subscription required.")
        return
    url = context.args[0] if context.args else None
    if not url:
        await update.message.reply_text("Usage: /youtube_slides <url>")
        return
    try:
        yt = YouTube(url)
        video_path = yt.streams.first().download()
        clip = VideoFileClip(video_path)
        frames = [clip.get_frame(t) for t in range(0, int(clip.duration), 10)]  # Every 10s
        for i, frame in enumerate(frames):
            img = Image.fromarray(frame)
            bio = BytesIO()
            img.save(bio, format='PNG')
            bio.seek(0)
            await update.message.reply_photo(bio, caption=f"Slide {i+1}")
        clip.close()
        os.unlink(video_path)
    except Exception as e:
        logger.exception("youtube_slides error")
        await update.message.reply_text(f"Error: {str(e)}")

async def create_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not check_subscription(user.id):
        await update.message.reply_text("Subscription required.")
        return
    if not update.message.photo:
        await update.message.reply_text("Send photos to create PDF.")
        return
    photos = update.message.photo
    images = []
    for photo in photos:
        file = await photo.get_file()
        data = await file.download_as_bytearray()
        images.append(Image.open(BytesIO(data)).convert('RGB'))
    pdf_path = tempfile.mktemp(suffix='.pdf')
    images[0].save(pdf_path, save_all=True, append_images=images[1:])
    await update.message.reply_document(open(pdf_path, 'rb'), filename='created.pdf')
    os.unlink(pdf_path)

async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(size) FROM files WHERE user_id = %s", (user.id,))
    used = cursor.fetchone()[0] or 0
    cursor.execute("SELECT storage_limit, expiry FROM subscriptions WHERE user_id = %s AND active = TRUE", (user.id,))
    sub = cursor.fetchone()
    cursor.close()
    conn.close()
    if sub:
        await update.message.reply_text(f"Used: {used/1024**3:.2f}GB / {sub[0]/1024**3:.2f}GB\nExpires: {sub[1]}")
    else:
        await update.message.reply_text("No active subscription.")

async def myplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT plan, expiry FROM subscriptions WHERE user_id = %s AND active = TRUE", (user.id,))
    sub = cursor.fetchone()
    cursor.close()
    conn.close()
    if sub:
        await update.message.reply_text(f"Plan: {sub[0]}\nExpires: {sub[1]}")
    else:
        await update.message.reply_text("No active subscription.")

# Main: register handlers and run
if __name__ == '__main__':
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('approve', approve_user))
    application.add_handler(CommandHandler('plans', plans))
    application.add_handler(CommandHandler('ticket', ticket))
    application.add_handler(CommandHandler('pay', pay_via_qr))
    application.add_handler(CommandHandler('adduser', adduser))
    application.add_handler(CommandHandler('myfiles', myfiles))
    application.add_handler(CommandHandler('senddocs', send_docs))
    application.add_handler(CommandHandler('youtube_download', youtube_download))
    application.add_handler(CommandHandler('youtube_audio', youtube_audio))
    application.add_handler(CommandHandler('youtube_slides', youtube_slides))
    application.add_handler(CommandHandler('create_pdf', create_pdf))
    application.add_handler(CommandHandler('mystats', mystats))
    application.add_handler(CommandHandler('myplan', myplan))

    # Message handlers
    application.add_handler(MessageHandler(filters.Document.ALL, upload_docs))
    application.add_handler(MessageHandler(filters.PHOTO, upload_images))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start scheduler
    scheduler.add_job(check_expiry, 'interval', hours=1)
    scheduler.start()

    # Run the bot
    application.run_polling()
