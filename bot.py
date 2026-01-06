import asyncio
import logging
import sys
import os
from datetime import datetime
from typing import Optional, Dict, List

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command, Text
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputFile,
    ChatType
)
from aiogram.utils.exceptions import BotBlocked, ChatNotFound
import asyncpg
from dotenv import load_dotenv

# Local imports
from database import Database
from admin_handlers import AdminHandlers, AdminStates
from tickets import TicketHandlers, TicketStates
from tools import ToolsHandlers
from user_handlers import UserHandlers, UserStates

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==================== BOT CONFIGURATION ====================

class Config:
    """Bot configuration from environment variables"""
    BOT_TOKEN = os.getenv('BOT_TOKEN', '8265547132:AAH0mkdd785RE9Dpwcqi3_aNgVVrd5vQFXo')
    ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', 0))
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 5432))
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_NAME = os.getenv('DB_NAME', 'filex_bot')
    SECRET_CODE = os.getenv('SECRET_CODE', '2008')
    ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
    HOST_URL = os.getenv('HOST_URL', 'https://your-app.herokuapp.com')
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 524288000))  # 500MB
    
    # Subscription plans (in INR)
    PLANS = {
        'monthly': {
            'name': 'Monthly',
            'price': 25,
            'duration_days': 30,
            'storage_gb': 5,
            'description': '₹25/month - 5GB Storage'
        },
        'quarterly': {
            'name': 'Quarterly',
            'price': 60,
            'duration_days': 90,
            'storage_gb': 15,
            'description': '₹60/3 months - 15GB Storage'
        },
        'half_year': {
            'name': 'Half Year',
            'price': 125,
            'duration_days': 180,
            'storage_gb': 30,
            'description': '₹125/6 months - 30GB Storage'
        },
        'yearly': {
            'name': 'Yearly',
            'price': 275,
            'duration_days': 365,
            'storage_gb': 100,
            'description': '₹275/year - 100GB Storage'
        }
    }

# ==================== BOT INITIALIZATION ====================

# Initialize bot and dispatcher
bot = Bot(token=Config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Initialize database
db = Database()

# Initialize handlers
admin_handlers = AdminHandlers(bot, db)
ticket_handlers = TicketHandlers(bot, db)
tools_handlers = ToolsHandlers(bot, db)
user_handlers = UserHandlers(bot, db)

# ==================== STARTUP & SHUTDOWN ====================

async def on_startup(dp: Dispatcher):
    """Initialize bot on startup"""
    logger.info("Starting TheFilex Bot...")
    
    try:
        # Initialize database connection
        await db.create_pool()
        logger.info("Database connection established")
        
        # Register handlers
        await register_handlers(dp)
        logger.info("Handlers registered")
        
        # Set bot commands menu
        await set_bot_commands()
        logger.info("Bot commands set")
        
        # Notify admin
        if Config.ADMIN_USER_ID:
            try:
                await bot.send_message(
                    Config.ADMIN_USER_ID,
                    "✅ *TheFilex Bot Started Successfully!*\n\n"
                    "Bot is now online and ready to receive commands.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify admin: {e}")
        
        logger.info("TheFilex Bot is ready!")
        
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        sys.exit(1)

async def on_shutdown(dp: Dispatcher):
    """Cleanup on shutdown"""
    logger.info("Shutting down TheFilex Bot...")
    
    # Close database connection
    if db.pool:
        await db.pool.close()
        logger.info("Database connection closed")
    
    # Close bot session
    await bot.close()
    logger.info("Bot session closed")

# ==================== BOT COMMANDS SETUP ====================

async def set_bot_commands():
    """Set bot commands menu"""
    commands = [
        types.BotCommand("start", "Start the bot"),
        types.BotCommand("help", "Show help information"),
        types.BotCommand("plans", "View subscription plans"),
        types.BotCommand("storage", "Check your storage"),
        types.BotCommand("upload", "Upload a file"),
        types.BotCommand("files", "View your files"),
        types.BotCommand("profile", "View your profile"),
        types.BotCommand("support", "Contact support"),
    ]
    
    await bot.set_my_commands(commands)

# ==================== HANDLER REGISTRATION ====================

async def register_handlers(dp: Dispatcher):
    """Register all bot handlers"""
    
    # Register admin handlers
    await admin_handlers.register_handlers(dp)
    
    # Register ticket handlers
    await ticket_handlers.register_handlers(dp)
    
    # Register tools handlers
    await tools_handlers.register_handlers(dp)
    
    # Register user handlers
    await user_handlers.register_handlers(dp)
    
    # Register common handlers
    dp.register_message_handler(start_command, Command("start"), state="*")
    dp.register_message_handler(help_command, Command("help"), state="*")
    dp.register_message_handler(plans_command, Command("plans"), state="*")
    dp.register_message_handler(cancel_command, Command("cancel"), state="*")
    dp.register_message_handler(echo_all, state="*")

# ==================== COMMON HANDLERS ====================

class CommonStates(StatesGroup):
    """Common states for basic operations"""
    AWAITING_FEEDBACK = State()

async def start_command(message: types.Message, state: FSMContext):
    """Handle /start command"""
    await state.finish()  # Clear any existing states
    
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    logger.info(f"New user start: {user_id} (@{username})")
    
    # Check if user exists
    async with db.pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT is_approved, is_banned FROM users WHERE user_id = $1",
            user_id
        )
        
        if user:
            if user['is_banned']:
                await message.answer(
                    "🚫 *Your account has been banned.*\n\n"
                    "If you believe this is an error, please contact support.",
                    parse_mode="Markdown"
                )
                return
            
            if not user['is_approved']:
                await message.answer(
                    "⏳ *Your account is pending approval.*\n\n"
                    "Please wait for admin approval. You will be notified once approved.",
                    parse_mode="Markdown"
                )
                return
            
            # User is approved, show main menu
            await show_main_menu(message)
            return
        
        # New user - check for secret code
        if message.get_args() == Config.SECRET_CODE:
            # User has secret code, proceed to registration
            await UserStates.AWAITING_PROFILE_LINK.set()
            
            # Save user info temporarily
            async with state.proxy() as data:
                data['user_id'] = user_id
                data['username'] = username
                data['first_name'] = first_name
                data['last_name'] = last_name
            
            await message.answer(
                "🔐 *Welcome to TheFilex Bot!*\n\n"
                "You've entered the correct secret code.\n\n"
                "To complete registration, please send your Telegram profile link:\n"
                "1. Go to your Telegram profile\n"
                "2. Click on 'Share Profile'\n"
                "3. Copy the link and send it here\n\n"
                "*Note:* Your account requires admin approval before you can use all features.",
                parse_mode="Markdown"
            )
        else:
            # No secret code or wrong code
            await message.answer(
                "🔐 *Welcome to TheFilex Bot!*\n\n"
                "This is a secure file storage system with subscription plans.\n\n"
                "*To get started:*\n"
                f"1. Use this link: https://t.me/{bot.username}?start={Config.SECRET_CODE}\n"
                "2. Or click /start with the secret code\n\n"
                f"*Secret Code:* `{Config.SECRET_CODE}`\n\n"
                "After entering the code, you'll need to submit your profile link for admin approval.",
                parse_mode="Markdown"
            )

async def show_main_menu(message: types.Message):
    """Show main menu to approved users"""
    user_id = message.from_user.id
    
    # Check user subscription status
    async with db.pool.acquire() as conn:
        subscription = await conn.fetchrow('''
            SELECT s.*, u.is_admin
            FROM subscriptions s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.user_id = $1 AND s.is_active = TRUE
        ''', user_id)
    
    # Create keyboard
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    if subscription:
        # User has active subscription
        plan_name = subscription['plan_type'].replace('_', ' ').title()
        used_gb = subscription['storage_used_gb'] or 0
        total_gb = subscription['storage_limit_gb']
        usage_percent = (used_gb / total_gb * 100) if total_gb > 0 else 0
        
        buttons = [
            InlineKeyboardButton("📤 Upload File", callback_data="upload_file"),
            InlineKeyboardButton("📁 My Files", callback_data="my_files"),
            InlineKeyboardButton("💾 Storage", callback_data="storage_info"),
            InlineKeyboardButton("🔄 Renew Plan", callback_data="renew_plan"),
            InlineKeyboardButton("⚙️ Tools", callback_data="tools_menu"),
            InlineKeyboardButton("👤 Profile", callback_data="user_profile"),
        ]
        
        if subscription['is_admin']:
            buttons.append(InlineKeyboardButton("🛠 Admin Panel", callback_data="admin_panel"))
        
        # Arrange buttons
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons):
                keyboard.add(buttons[i], buttons[i+1])
            else:
                keyboard.add(buttons[i])
        
        welcome_text = (
            f"👋 *Welcome back, {message.from_user.first_name}!*\n\n"
            f"📊 *Your Subscription:*\n"
            f"• Plan: {plan_name}\n"
            f"• Storage: {used_gb:.2f} GB / {total_gb} GB ({usage_percent:.1f}%)\n"
            f"• Expiry: {subscription['expiry_date'].strftime('%Y-%m-%d')}\n\n"
            "Select an option below:"
        )
    else:
        # User needs subscription
        buttons = [
            InlineKeyboardButton("💰 View Plans", callback_data="view_plans"),
            InlineKeyboardButton("💳 Subscribe", callback_data="subscribe"),
            InlineKeyboardButton("👤 Profile", callback_data="user_profile"),
            InlineKeyboardButton("❓ Help", callback_data="help"),
        ]
        
        # Arrange buttons
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons):
                keyboard.add(buttons[i], buttons[i+1])
            else:
                keyboard.add(buttons[i])
        
        welcome_text = (
            f"👋 *Welcome, {message.from_user.first_name}!*\n\n"
            "You don't have an active subscription yet.\n\n"
            "Choose a plan to start uploading and managing files:"
        )
    
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")

async def help_command(message: types.Message, state: FSMContext):
    """Handle /help command"""
    await state.finish()
    
    help_text = (
        "🆘 *TheFilex Bot Help*\n\n"
        
        "*Available Commands:*\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/plans - View subscription plans\n"
        "/storage - Check your storage usage\n"
        "/upload - Upload a file\n"
        "/files - View your files\n"
        "/profile - View your profile\n"
        "/support - Contact support\n\n"
        
        "*Subscription Plans:*\n"
        "• ₹25/month - 5GB Storage\n"
        "• ₹60/3 months - 15GB Storage\n"
        "• ₹125/6 months - 30GB Storage\n"
        "• ₹275/year - 100GB Storage\n\n"
        
        "*Features:*\n"
        "✅ Secure file storage\n"
        "✅ End-to-end encryption\n"
        "✅ File sharing\n"
        "✅ YouTube tools\n"
        "✅ PDF generation\n"
        "✅ 24/7 hosting\n\n"
        
        "*Need Help?*\n"
        "Use /support to contact our team."
    )
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("📞 Contact Support", callback_data="contact_support"))
    
    await message.answer(help_text, parse_mode="Markdown", reply_markup=keyboard)

async def plans_command(message: types.Message, state: FSMContext):
    """Handle /plans command"""
    await state.finish()
    
    plans_text = "💰 *Subscription Plans*\n\n"
    
    for plan_id, plan in Config.PLANS.items():
        plans_text += (
            f"*{plan['name']} Plan*\n"
            f"• Price: ₹{plan['price']}\n"
            f"• Duration: {plan['duration_days']} days\n"
            f"• Storage: {plan['storage_gb']} GB\n"
            f"• Description: {plan['description']}\n\n"
        )
    
    plans_text += "Click the button below to subscribe:"
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("💳 Subscribe Now", callback_data="subscribe"))
    
    await message.answer(plans_text, parse_mode="Markdown", reply_markup=keyboard)

async def cancel_command(message: types.Message, state: FSMContext):
    """Cancel any ongoing operation"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("ℹ️ No active operation to cancel.")
        return
    
    await state.finish()
    await message.answer(
        "❌ Operation cancelled.",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Show main menu
    await show_main_menu(message)

async def echo_all(message: types.Message):
    """Handle all other messages"""
    # Log the message
    logger.debug(f"Message from {message.from_user.id}: {message.text}")
    
    # Check if user is approved
    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT is_approved, is_banned FROM users WHERE user_id = $1",
            user_id
        )
    
    if not user:
        # New user without registration
        await message.answer(
            "🔐 *Welcome!*\n\n"
            "You need to register first. Please use /start with the secret code.\n"
            f"Secret Code: `{Config.SECRET_CODE}`",
            parse_mode="Markdown"
        )
        return
    
    if user['is_banned']:
        await message.answer("🚫 Your account has been banned.")
        return
    
    if not user['is_approved']:
        await message.answer("⏳ Your account is pending admin approval.")
        return
    
    # Update last active timestamp
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET last_active = NOW() WHERE user_id = $1",
            user_id
        )
    
    # If no specific handler matched, show main menu
    await show_main_menu(message)

# ==================== CALLBACK QUERY HANDLERS ====================

@dp.callback_query_handler(lambda c: c.data == "main_menu")
async def main_menu_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Handle main menu callback"""
    await state.finish()
    await callback_query.message.delete()
    await show_main_menu(callback_query.message)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "help")
async def help_callback(callback_query: types.CallbackQuery):
    """Handle help callback"""
    await help_command(callback_query.message, None)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "view_plans")
async def view_plans_callback(callback_query: types.CallbackQuery):
    """Handle view plans callback"""
    await plans_command(callback_query.message, None)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "subscribe")
async def subscribe_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Handle subscribe callback"""
    # Show plan selection
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    for plan_id, plan in Config.PLANS.items():
        keyboard.add(InlineKeyboardButton(
            plan['description'],
            callback_data=f"select_plan_{plan_id}"
        ))
    
    await callback_query.message.edit_text(
        "💰 *Choose a Subscription Plan*\n\n"
        "Select a plan to continue:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("select_plan_"))
async def select_plan_callback(callback_query: types.CallbackQuery, state: FSMContext):
    """Handle plan selection"""
    plan_id = callback_query.data.replace("select_plan_", "")
    
    if plan_id not in Config.PLANS:
        await callback_query.answer("❌ Invalid plan selected.")
        return
    
    plan = Config.PLANS[plan_id]
    
    # Save plan selection
    async with state.proxy() as data:
        data['selected_plan'] = plan_id
    
    # Show payment options
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("💳 UPI / QR Code", callback_data=f"pay_upi_{plan_id}"),
        InlineKeyboardButton("🏦 Bank Transfer", callback_data=f"pay_bank_{plan_id}"),
        InlineKeyboardButton("💵 Cash / Offline", callback_data=f"pay_cash_{plan_id}"),
        InlineKeyboardButton("🔙 Back", callback_data="subscribe")
    )
    
    await callback_query.message.edit_text(
        f"🛒 *Plan Selected: {plan['name']}*\n\n"
        f"• Price: ₹{plan['price']}\n"
        f"• Duration: {plan['duration_days']} days\n"
        f"• Storage: {plan['storage_gb']} GB\n\n"
        "Choose payment method:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    await callback_query.answer()

# ==================== ERROR HANDLING ====================

@dp.errors_handler()
async def errors_handler(update: types.Update, exception: Exception):
    """Handle errors"""
    try:
        raise exception
    except BotBlocked:
        logger.warning(f"Bot blocked by user: {update.message.from_user.id}")
    except ChatNotFound:
        logger.warning(f"Chat not found: {update.message.from_user.id}")
    except Exception as e:
        logger.error(f"Update {update} caused error: {e}")
    
    return True

# ==================== UTILITY FUNCTIONS ====================

async def notify_admin(message: str):
    """Send notification to admin"""
    if Config.ADMIN_USER_ID:
        try:
            await bot.send_message(Config.ADMIN_USER_ID, message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

async def check_user_access(user_id: int) -> bool:
    """Check if user has access to bot features"""
    async with db.pool.acquire() as conn:
        user = await conn.fetchrow('''
            SELECT u.is_approved, u.is_banned, s.is_active
            FROM users u
            LEFT JOIN subscriptions s ON u.user_id = s.user_id AND s.is_active = TRUE
            WHERE u.user_id = $1
        ''', user_id)
    
    if not user:
        return False
    
    if user['is_banned']:
        return False
    
    if not user['is_approved']:
        return False
    
    if not user['is_active']:
        # User needs subscription
        return False
    
    return True

# ==================== MAIN EXECUTION ====================

if __name__ == '__main__':
    logger.info("Starting TheFilex Bot...")
    
    # Create required directories
    os.makedirs('data/files', exist_ok=True)
    os.makedirs('data/qrcodes', exist_ok=True)
    os.makedirs('data/temp', exist_ok=True)
    os.makedirs('data/backups', exist_ok=True)
    
    # Start the bot
    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        timeout=60
    )