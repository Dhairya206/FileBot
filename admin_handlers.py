import logging
import asyncio
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from aiogram import Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command, Text
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputFile
)
from aiogram.utils.exceptions import BotBlocked, ChatNotFound
import asyncpg
import pandas as pd
from io import BytesIO
import qrcode
from database import Database
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# ==================== STATES ====================
class AdminStates(StatesGroup):
    """FSM states for admin operations"""
    AWAITING_SECRET = State()
    AWAITING_USERNAME = State()
    AWAITING_PROFILE_LINK = State()
    MANAGE_USER = State()
    SEND_BROADCAST = State()
    SEND_BROADCAST_CONFIRM = State()
    VIEW_STATS = State()
    MANAGE_TICKET = State()
    UPDATE_STORAGE = State()
    APPROVE_USER = State()
    BAN_USER = State()
    SEARCH_USER = State()
    ADD_STORAGE = State()

# ==================== ADMIN HANDLERS ====================
class AdminHandlers:
    def __init__(self, bot, db: Database):
        self.bot = bot
        self.db = db
        self.admin_id = int(os.getenv('ADMIN_USER_ID', 0))
        self.secret_code = os.getenv('SECRET_CODE', '2008')
        
    async def register_handlers(self, dp: Dispatcher):
        """Register all admin command handlers"""
        
        # Admin authentication
        dp.register_message_handler(
            self.admin_start, 
            Command("admin", "a"), 
            state="*"
        )
        dp.register_message_handler(
            self.verify_secret, 
            state=AdminStates.AWAITING_SECRET
        )
        
        # Admin panel navigation
        dp.register_callback_query_handler(
            self.admin_dashboard, 
            lambda c: c.data == "admin_panel"
        )
        dp.register_callback_query_handler(
            self.handle_admin_actions, 
            lambda c: c.data.startswith("admin_")
        )
        
        # User approval flow
        dp.register_message_handler(
            self.handle_profile_link, 
            state=AdminStates.AWAITING_PROFILE_LINK
        )
        dp.register_callback_query_handler(
            self.handle_approval_decision,
            lambda c: c.data.startswith("approve_") or c.data.startswith("reject_")
        )
        
        # Broadcasting
        dp.register_message_handler(
            self.handle_broadcast_message, 
            state=AdminStates.SEND_BROADCAST
        )
        dp.register_callback_query_handler(
            self.confirm_broadcast,
            lambda c: c.data.startswith("broadcast_confirm_")
        )
        dp.register_callback_query_handler(
            self.cancel_broadcast,
            lambda c: c.data == "broadcast_cancel"
        )
        
        # User management callbacks
        dp.register_callback_query_handler(
            self.handle_user_management,
            lambda c: c.data.startswith("user_")
        )
        
        # Ticket management callbacks
        dp.register_callback_query_handler(
            self.handle_ticket_management,
            lambda c: c.data.startswith("ticket_")
        )
        
        # Direct admin commands
        dp.register_message_handler(
            self.stats_command, 
            Command("stats"), 
            is_admin=True
        )
        dp.register_message_handler(
            self.users_command, 
            Command("users"), 
            is_admin=True
        )
        dp.register_message_handler(
            self.tickets_command, 
            Command("tickets"), 
            is_admin=True
        )
        dp.register_message_handler(
            self.broadcast_command, 
            Command("broadcast"), 
            is_admin=True
        )
        dp.register_message_handler(
            self.storage_command, 
            Command("storage"), 
            is_admin=True
        )
        dp.register_message_handler(
            self.ban_command, 
            Command("ban"), 
            is_admin=True
        )
        dp.register_message_handler(
            self.unban_command, 
            Command("unban"), 
            is_admin=True
        )
        dp.register_message_handler(
            self.approve_command, 
            Command("approve"), 
            is_admin=True
        )
        dp.register_message_handler(
            self.revenue_command, 
            Command("revenue"), 
            is_admin=True
        )
        dp.register_message_handler(
            self.backup_command, 
            Command("backup"), 
            is_admin=True
        )
        dp.register_message_handler(
            self.search_command, 
            Command("search"), 
            is_admin=True
        )
        
        # State handlers
        dp.register_message_handler(
            self.process_user_search,
            state=AdminStates.SEARCH_USER
        )
        dp.register_message_handler(
            self.process_add_storage,
            state=AdminStates.ADD_STORAGE
        )
    
    # ==================== ADMIN AUTHENTICATION ====================
    
    async def admin_start(self, message: types.Message, state: FSMContext):
        """Start admin authentication process"""
        user_id = message.from_user.id
        
        # Check if already admin
        async with self.db.pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT is_admin FROM users WHERE user_id = $1",
                user_id
            )
            
            if user and user['is_admin']:
                await self.show_admin_panel(message)
                await state.finish()
                return
        
        # Check if this is the main admin (from .env)
        if user_id == self.admin_id:
            # Auto-promote main admin
            async with self.db.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO users (user_id, username, first_name, last_name, is_admin, is_approved)
                    VALUES ($1, $2, $3, $4, TRUE, TRUE)
                    ON CONFLICT (user_id) DO UPDATE 
                    SET is_admin = TRUE, is_approved = TRUE,
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name
                ''', user_id, message.from_user.username, 
                   message.from_user.first_name, message.from_user.last_name)
            
            await message.answer("👑 *Welcome, Main Admin!*", parse_mode="Markdown")
            await self.show_admin_panel(message)
            await state.finish()
            return
        
        # For other users, require secret code
        await AdminStates.AWAITING_SECRET.set()
        await message.answer(
            "🔐 *Admin Authentication*\n\n"
            "Enter the admin secret code:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
    
    async def verify_secret(self, message: types.Message, state: FSMContext):
        """Verify admin secret code"""
        if message.text == self.secret_code:
            user_id = message.from_user.id
            
            # Set user as admin
            async with self.db.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO users (user_id, username, first_name, last_name, is_admin, is_approved)
                    VALUES ($1, $2, $3, $4, TRUE, TRUE)
                    ON CONFLICT (user_id) DO UPDATE 
                    SET is_admin = TRUE, is_approved = TRUE
                ''', user_id, message.from_user.username, 
                   message.from_user.first_name, message.from_user.last_name)
                
                # Log admin promotion
                await conn.execute('''
                    INSERT INTO admin_logs (admin_id, action, target_user_id, details)
                    VALUES ($1, 'admin_promotion', $2, 'User entered secret code')
                ''', user_id, user_id)
            
            await state.finish()
            await message.answer(
                "✅ *Successfully promoted to Admin!*\n\n"
                "You now have access to the admin panel.",
                parse_mode="Markdown"
            )
            await self.show_admin_panel(message)
        else:
            await message.answer("❌ Invalid secret code. Access denied.")
            await state.finish()
    
    # ==================== ADMIN PANEL ====================
    
    async def show_admin_panel(self, message: types.Message):
        """Display main admin dashboard with comprehensive stats"""
        async with self.db.pool.acquire() as conn:
            # Quick stats
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            pending_users = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE is_approved = FALSE AND is_banned = FALSE"
            )
            active_tickets = await conn.fetchval(
                "SELECT COUNT(*) FROM payment_tickets WHERE status = 'pending'"
            )
            storage_used = await conn.fetchval(
                "SELECT COALESCE(SUM(storage_used_gb), 0) FROM subscriptions WHERE is_active = TRUE"
            )
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        
        buttons = [
            InlineKeyboardButton("📊 Dashboard", callback_data="admin_dashboard"),
            InlineKeyboardButton("👥 Users", callback_data="admin_users"),
            InlineKeyboardButton("⏳ Pending", callback_data="admin_pending"),
            InlineKeyboardButton("🎫 Tickets", callback_data="admin_tickets"),
            InlineKeyboardButton("💾 Storage", callback_data="admin_storage"),
            InlineKeyboardButton("💰 Revenue", callback_data="admin_revenue"),
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton("🔍 Search", callback_data="admin_search"),
            InlineKeyboardButton("📈 Stats", callback_data="admin_stats"),
            InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings"),
            InlineKeyboardButton("📦 Backup", callback_data="admin_backup"),
            InlineKeyboardButton("📋 Logs", callback_data="admin_logs"),
        ]
        
        # Arrange buttons in grid
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons):
                keyboard.add(buttons[i], buttons[i+1])
            else:
                keyboard.add(buttons[i])
        
        welcome_text = (
            "🛠 *Admin Control Panel*\n\n"
            f"📊 Quick Stats:\n"
            f"• Total Users: {total_users}\n"
            f"• Pending Approvals: {pending_users}\n"
            f"• Active Tickets: {active_tickets}\n"
            f"• Storage Used: {storage_used:.2f} GB\n\n"
            "Select an option below:"
        )
        
        await message.answer(
            welcome_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    async def handle_admin_actions(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Handle all admin panel button clicks"""
        action = callback_query.data.replace("admin_", "")
        
        try:
            if action == "dashboard":
                await self.show_admin_panel(callback_query.message)
            elif action == "users":
                await self.show_user_management(callback_query.message)
            elif action == "pending":
                await self.show_pending_approvals(callback_query.message)
            elif action == "tickets":
                await self.show_ticket_management(callback_query.message)
            elif action == "storage":
                await self.show_storage_overview(callback_query.message)
            elif action == "revenue":
                await self.show_revenue_stats(callback_query.message)
            elif action == "broadcast":
                await self.initiate_broadcast(callback_query.message, state)
            elif action == "search":
                await self.search_user_prompt(callback_query.message, state)
            elif action == "stats":
                await self.show_detailed_statistics(callback_query.message)
            elif action == "settings":
                await self.show_settings(callback_query.message)
            elif action == "backup":
                await self.create_backup(callback_query.message)
            elif action == "logs":
                await self.show_recent_logs(callback_query.message)
        except Exception as e:
            logger.error(f"Error in admin action {action}: {e}")
            await callback_query.message.answer(f"❌ Error: {str(e)}")
        
        await callback_query.answer()
    
    # ==================== USER MANAGEMENT ====================
    
    async def users_command(self, message: types.Message):
        """Command: /users - Show user management"""
        await self.show_user_management(message)
    
    async def show_user_management(self, message: types.Message, page: int = 0):
        """Display user management interface"""
        async with self.db.pool.acquire() as conn:
            users = await conn.fetch('''
                SELECT user_id, username, first_name, last_name, 
                       is_approved, is_banned, join_date, last_active
                FROM users 
                ORDER BY join_date DESC
                LIMIT 10 OFFSET $1
            ''', page * 10)
            
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        
        if not users:
            await message.answer("📭 No users found.")
            return
        
        keyboard = InlineKeyboardMarkup(row_width=3)
        
        for user in users:
            status = "✅" if user['is_approved'] else "⏳"
            status = "🚫" if user['is_banned'] else status
            username = user['username'] or f"{user['first_name']} {user['last_name'] or ''}"
            
            keyboard.add(InlineKeyboardButton(
                f"{status} {username[:15]}",
                callback_data=f"user_detail_{user['user_id']}"
            ))
        
        # Pagination
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(
                "⬅️ Previous",
                callback_data=f"users_page_{page-1}"
            ))
        
        if (page + 1) * 10 < total_users:
            nav_buttons.append(InlineKeyboardButton(
                "Next ➡️",
                callback_data=f"users_page_{page+1}"
            ))
        
        if nav_buttons:
            keyboard.row(*nav_buttons)
        
        # Add quick actions
        keyboard.row(
            InlineKeyboardButton("📥 Export CSV", callback_data="export_users_csv"),
            InlineKeyboardButton("🔄 Refresh", callback_data="admin_users")
        )
        
        await message.answer(
            f"👥 *User Management*\n\n"
            f"Page {page + 1} of {(total_users + 9) // 10}\n"
            f"Total Users: {total_users}\n\n"
            "Click on a user to manage:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    async def handle_user_management(self, callback_query: types.CallbackQuery):
        """Handle user management callbacks"""
        data = callback_query.data
        
        if data.startswith("user_detail_"):
            user_id = int(data.replace("user_detail_", ""))
            await self.show_user_detail(callback_query.message, user_id)
        
        elif data.startswith("users_page_"):
            page = int(data.replace("users_page_", ""))
            await self.show_user_management(callback_query.message, page)
        
        elif data == "export_users_csv":
            await self.export_users_csv(callback_query.message)
        
        await callback_query.answer()
    
    async def show_user_detail(self, message: types.Message, user_id: int):
        """Show detailed user information"""
        async with self.db.pool.acquire() as conn:
            user = await conn.fetchrow('''
                SELECT u.*, 
                       s.plan_type, s.storage_limit_gb, s.storage_used_gb,
                       s.expiry_date, s.is_active as sub_active
                FROM users u
                LEFT JOIN subscriptions s ON u.user_id = s.user_id AND s.is_active = TRUE
                WHERE u.user_id = $1
            ''', user_id)
            
            if not user:
                await message.answer("❌ User not found.")
                return
            
            # Get user files count
            files_count = await conn.fetchval(
                "SELECT COUNT(*) FROM files WHERE user_id = $1",
                user_id
            )
            
            # Get payment history
            payments = await conn.fetch(
                "SELECT plan_type, amount, status, created_at "
                "FROM payment_tickets WHERE user_id = $1 ORDER BY created_at DESC LIMIT 5",
                user_id
            )
        
        # Format user info
        status_emoji = "✅" if user['is_approved'] else "⏳"
        status_emoji = "🚫" if user['is_banned'] else status_emoji
        status_text = "Approved" if user['is_approved'] else "Pending"
        status_text = "Banned" if user['is_banned'] else status_text
        
        user_info = (
            f"👤 *User Details*\n\n"
            f"🆔 ID: `{user['user_id']}`\n"
            f"👤 Username: @{user['username'] or 'N/A'}\n"
            f"📛 Name: {user['first_name']} {user['last_name'] or ''}\n"
            f"🔗 Profile: {user['profile_link'] or 'N/A'}\n"
            f"📅 Joined: {user['join_date'].strftime('%Y-%m-%d %H:%M')}\n"
            f"🕐 Last Active: {user['last_active'].strftime('%Y-%m-%d %H:%M')}\n"
            f"📊 Status: {status_emoji} {status_text}\n"
            f"👑 Admin: {'✅ Yes' if user['is_admin'] else '❌ No'}\n\n"
            
            f"💾 *Subscription*\n"
            f"• Plan: {user['plan_type'] or 'None'}\n"
            f"• Storage: {user['storage_used_gb'] or 0:.2f} GB / {user['storage_limit_gb'] or 0} GB\n"
            f"• Expiry: {user['expiry_date'].strftime('%Y-%m-%d') if user['expiry_date'] else 'N/A'}\n"
            f"• Active: {'✅ Yes' if user['sub_active'] else '❌ No'}\n"
            f"• Files: {files_count}\n"
        )
        
        # Add payment history
        if payments:
            user_info += "\n💰 *Recent Payments:*\n"
            for payment in payments:
                user_info += f"• {payment['plan_type']}: ₹{payment['amount']} ({payment['status']})\n"
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        
        # Action buttons based on user status
        if not user['is_approved']:
            keyboard.add(InlineKeyboardButton(
                "✅ Approve User",
                callback_data=f"approve_{user_id}"
            ))
        
        if not user['is_banned']:
            keyboard.add(InlineKeyboardButton(
                "🚫 Ban User",
                callback_data=f"ban_{user_id}"
            ))
        else:
            keyboard.add(InlineKeyboardButton(
                "🔓 Unban User",
                callback_data=f"unban_{user_id}"
            ))
        
        keyboard.add(InlineKeyboardButton(
            "💾 Add Storage",
            callback_data=f"add_storage_{user_id}"
        ))
        
        keyboard.add(InlineKeyboardButton(
            "📊 Extend Plan",
            callback_data=f"extend_plan_{user_id}"
        ))
        
        keyboard.row(
            InlineKeyboardButton("📝 Message User", callback_data=f"message_user_{user_id}"),
            InlineKeyboardButton("🔙 Back", callback_data="admin_users")
        )
        
        await message.answer(user_info, reply_markup=keyboard, parse_mode="Markdown")
    
    # ==================== USER APPROVAL SYSTEM ====================
    
    async def approve_command(self, message: types.Message):
        """Command: /approve <user_id> - Approve a user"""
        try:
            user_id = int(message.get_args())
            await self.approve_user(message, user_id)
        except ValueError:
            await message.answer("❌ Usage: /approve <user_id>")
    
    async def show_pending_approvals(self, message: types.Message):
        """Show list of users pending approval"""
        async with self.db.pool.acquire() as conn:
            pending_users = await conn.fetch('''
                SELECT user_id, username, first_name, last_name, 
                       profile_link, join_date, secret_code
                FROM users 
                WHERE is_approved = FALSE AND is_banned = FALSE
                ORDER BY join_date DESC
            ''')
        
        if not pending_users:
            await message.answer("✅ No pending approvals.")
            return
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        
        for user in pending_users:
            username = user['username'] or f"{user['first_name']} {user['last_name'] or ''}"
            keyboard.add(InlineKeyboardButton(
                f"👤 {username[:20]}",
                callback_data=f"approve_detail_{user['user_id']}"
            ))
        
        await message.answer(
            f"⏳ *Pending Approvals* ({len(pending_users)} users)\n\n"
            "Click on a user to review:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    async def handle_profile_link(self, message: types.Message, state: FSMContext):
        """Handle user profile link submission"""
        async with state.proxy() as data:
            user_id = data['user_id']
            username = data['username']
        
        profile_link = message.text
        
        # Update user with profile link
        async with self.db.pool.acquire() as conn:
            await conn.execute('''
                UPDATE users 
                SET profile_link = $1, secret_code = $2
                WHERE user_id = $3
            ''', profile_link, "PENDING", user_id)
            
            # Notify admin
            admin_notification = (
                f"📝 *New User Registration*\n\n"
                f"👤 Username: @{username}\n"
                f"🆔 User ID: `{user_id}`\n"
                f"🔗 Profile: {profile_link}\n\n"
                f"Click below to approve or reject:"
            )
            
            keyboard = InlineKeyboardMarkup(row_width=2)
            keyboard.add(
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
            )
            
            await self.bot.send_message(
                self.admin_id,
                admin_notification,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        
        await state.finish()
        await message.answer(
            "✅ Profile submitted! Please wait for admin approval.\n"
            "You'll receive a notification once approved."
        )
    
    async def handle_approval_decision(self, callback_query: types.CallbackQuery):
        """Handle approve/reject decisions"""
        data = callback_query.data
        
        if data.startswith("approve_"):
            user_id = int(data.replace("approve_", ""))
            await self.approve_user(callback_query.message, user_id, callback_query.from_user.id)
        
        elif data.startswith("reject_"):
            user_id = int(data.replace("reject_", ""))
            await self.reject_user(callback_query.message, user_id, callback_query.from_user.id)
        
        await callback_query.answer()
    
    async def approve_user(self, message: types.Message, user_id: int, admin_id: int = None):
        """Approve a user"""
        admin_id = admin_id or message.from_user.id
        
        async with self.db.pool.acquire() as conn:
            # Update user status
            await conn.execute('''
                UPDATE users 
                SET is_approved = TRUE, secret_code = NULL
                WHERE user_id = $1
            ''', user_id)
            
            # Log the action
            await conn.execute('''
                INSERT INTO admin_logs (admin_id, action, target_user_id, details)
                VALUES ($1, 'user_approval', $2, 'User approved via admin panel')
            ''', admin_id, user_id)
            
            # Get user info for notification
            user = await conn.fetchrow(
                "SELECT username, first_name FROM users WHERE user_id = $1",
                user_id
            )
        
        # Notify user
        try:
            await self.bot.send_message(
                user_id,
                "🎉 *Your account has been approved!*\n\n"
                "You can now use all features of TheFilex Bot.\n"
                "Use /start to begin.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Could not notify user {user_id}: {e}")
        
        # Confirm to admin
        username = user['username'] or user['first_name']
        await message.answer(f"✅ User @{username} has been approved.")
    
    async def reject_user(self, message: types.Message, user_id: int, admin_id: int):
        """Reject a user"""
        async with self.db.pool.acquire() as conn:
            # Delete user (or mark as rejected)
            await conn.execute("DELETE FROM users WHERE user_id = $1", user_id)
            
            # Log the action
            await conn.execute('''
                INSERT INTO admin_logs (admin_id, action, target_user_id, details)
                VALUES ($1, 'user_rejection', $2, 'User rejected via admin panel')
            ''', admin_id, user_id)
        
        # Notify user
        try:
            await self.bot.send_message(
                user_id,
                "❌ *Your registration has been rejected.*\n\n"
                "If you believe this is an error, please contact support.",
                parse_mode="Markdown"
            )
        except:
            pass
        
        await message.answer("❌ User has been rejected and removed.")
    
    # ==================== BAN/UNBAN SYSTEM ====================
    
    async def ban_command(self, message: types.Message):
        """Command: /ban <user_id> <reason> - Ban a user"""
        args = message.get_args().split()
        if len(args) < 1:
            await message.answer("❌ Usage: /ban <user_id> [reason]")
            return
        
        try:
            user_id = int(args[0])
            reason = " ".join(args[1:]) if len(args) > 1 else "No reason provided"
            await self.ban_user(message, user_id, reason)
        except ValueError:
            await message.answer("❌ Invalid user ID")
    
    async def unban_command(self, message: types.Message):
        """Command: /unban <user_id> - Unban a user"""
        try:
            user_id = int(message.get_args())
            await self.unban_user(message, user_id)
        except ValueError:
            await message.answer("❌ Usage: /unban <user_id>")
    
    async def ban_user(self, message: types.Message, user_id: int, reason: str = ""):
        """Ban a user"""
        async with self.db.pool.acquire() as conn:
            # Update user status
            await conn.execute('''
                UPDATE users 
                SET is_banned = TRUE, is_approved = FALSE
                WHERE user_id = $1
            ''', user_id)
            
            # Log the action
            await conn.execute('''
                INSERT INTO admin_logs (admin_id, action, target_user_id, details)
                VALUES ($1, 'user_ban', $2, $3)
            ''', message.from_user.id, user_id, f"Reason: {reason}")
            
            # Get username
            user = await conn.fetchrow(
                "SELECT username FROM users WHERE user_id = $1",
                user_id
            )
        
        # Notify user
        ban_message = (
            "🚫 *Your account has been banned!*\n\n"
            f"Reason: {reason}\n\n"
            "If you believe this is an error, contact support."
        )
        
        try:
            await self.bot.send_message(user_id, ban_message, parse_mode="Markdown")
        except:
            pass
        
        username = user['username'] if user else str(user_id)
        await message.answer(f"🚫 User @{username} has been banned.")
    
    async def unban_user(self, message: types.Message, user_id: int):
        """Unban a user"""
        async with self.db.pool.acquire() as conn:
            # Update user status
            await conn.execute('''
                UPDATE users 
                SET is_banned = FALSE, is_approved = TRUE
                WHERE user_id = $1
            ''', user_id)
            
            # Log the action
            await conn.execute('''
                INSERT INTO admin_logs (admin_id, action, target_user_id, details)
                VALUES ($1, 'user_unban', $2, 'User unbanned')
            ''', message.from_user.id, user_id)
            
            # Get username
            user = await conn.fetchrow(
                "SELECT username FROM users WHERE user_id = $1",
                user_id
            )
        
        # Notify user
        try:
            await self.bot.send_message(
                user_id,
                "✅ *Your account has been unbanned!*\n\n"
                "You can now use the bot again.",
                parse_mode="Markdown"
            )
        except:
            pass
        
        username = user['username'] if user else str(user_id)
        await message.answer(f"✅ User @{username} has been unbanned.")
    
    # ==================== PAYMENT TICKET MANAGEMENT ====================
    
    async def tickets_command(self, message: types.Message):
        """Command: /tickets - Show payment tickets"""
        await self.show_ticket_management(message)
    
    async def show_ticket_management(self, message: types.Message, status: str = "pending"):
        """Display payment ticket management"""
        async with self.db.pool.acquire() as conn:
            tickets = await conn.fetch('''
                SELECT t.*, u.username, u.first_name
                FROM payment_tickets t
                JOIN users u ON t.user_id = u.user_id
                WHERE t.status = $1
                ORDER BY t.created_at DESC
                LIMIT 20
            ''', status)
            
            counts = await conn.fetchrow('''
                SELECT 
                    COUNT(*) FILTER (WHERE status = 'pending') as pending,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) as total
                FROM payment_tickets
            ''')
        
        if not tickets:
            await message.answer(f"📭 No {status} tickets found.")
            return
        
        # Status filter buttons
        keyboard = InlineKeyboardMarkup(row_width=3)
        keyboard.row(
            InlineKeyboardButton(
                f"⏳ Pending ({counts['pending']})",
                callback_data="tickets_pending"
            ),
            InlineKeyboardButton(
                f"✅ Completed ({counts['completed']})",
                callback_data="tickets_completed"
            ),
            InlineKeyboardButton(
                f"❌ Failed ({counts['failed']})",
                callback_data="tickets_failed"
            )
        )
        
        # Ticket list
        for ticket in tickets:
            username = ticket['username'] or ticket['first_name']
            keyboard.add(InlineKeyboardButton(
                f"🎫 {username[:15]} - ₹{ticket['amount']} ({ticket['plan_type']})",
                callback_data=f"ticket_detail_{ticket['ticket_id']}"
            ))
        
        await message.answer(
            f"🎫 *Payment Tickets - {status.upper()}*\n\n"
            f"Total: {counts['total']} | Pending: {counts['pending']} | "
            f"Completed: {counts['completed']} | Failed: {counts['failed']}\n\n"
            "Click on a ticket to manage:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    async def handle_ticket_management(self, callback_query: types.CallbackQuery):
        """Handle ticket management callbacks"""
        data = callback_query.data
        
        if data == "tickets_pending":
            await self.show_ticket_management(callback_query.message, "pending")
        elif data == "tickets_completed":
            await self.show_ticket_management(callback_query.message, "completed")
        elif data == "tickets_failed":
            await self.show_ticket_management(callback_query.message, "failed")
        elif data.startswith("ticket_detail_"):
            ticket_id = data.replace("ticket_detail_", "")
            await self.show_ticket_detail(callback_query.message, ticket_id)
        
        await callback_query.answer()
    
    async def show_ticket_detail(self, message: types.Message, ticket_id: str):
        """Show detailed ticket information"""
        async with self.db.pool.acquire() as conn:
            ticket = await conn.fetchrow('''
                SELECT t.*, u.username, u.first_name, u.user_id
                FROM payment_tickets t
                JOIN users u ON t.user_id = u.user_id
                WHERE t.ticket_id = $1
            ''', ticket_id)
            
            if not ticket:
                await message.answer("❌ Ticket not found.")
                return
        
        status_emoji = {
            'pending': '⏳',
            'completed': '✅',
            'failed': '❌'
        }.get(ticket['status'], '❓')
        
        ticket_info = (
            f"🎫 *Ticket Details*\n\n"
            f"🆔 Ticket ID: `{ticket['ticket_id']}`\n"
            f"👤 User: @{ticket['username'] or ticket['first_name']}\n"
            f"🆔 User ID: `{ticket['user_id']}`\n"
            f"📦 Plan: {ticket['plan_type']}\n"
            f"💰 Amount: ₹{ticket['amount']}\n"
            f"📊 Status: {status_emoji} {ticket['status'].upper()}\n"
            f"💳 Method: {ticket['payment_method'] or 'N/A'}\n"
            f"📅 Created: {ticket['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
            f"🔄 Processed: {ticket['processed_at'].strftime('%Y-%m-%d %H:%M') if ticket['processed_at'] else 'N/A'}\n"
            f"📝 Notes: {ticket['admin_notes'] or 'None'}\n"
        )
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        
        if ticket['status'] == 'pending':
            keyboard.add(
                InlineKeyboardButton("✅ Mark Complete", callback_data=f"ticket_complete_{ticket_id}"),
                InlineKeyboardButton("❌ Mark Failed", callback_data=f"ticket_fail_{ticket_id}")
            )
        
        keyboard.add(InlineKeyboardButton("💬 Message User", callback_data=f"message_user_{ticket['user_id']}"))
        keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="admin_tickets"))
        
        await message.answer(ticket_info, reply_markup=keyboard, parse_mode="Markdown")
    
    # ==================== STORAGE MANAGEMENT ====================
    
    async def storage_command(self, message: types.Message):
        """Command: /storage - Show storage overview"""
        await self.show_storage_overview(message)
    
    async def show_storage_overview(self, message: types.Message):
        """Display storage usage overview"""
        async with self.db.pool.acquire() as conn:
            # Storage stats
            stats = await conn.fetchrow('''
                SELECT 
                    COALESCE(SUM(storage_limit_gb), 0) as total_limit,
                    COALESCE(SUM(storage_used_gb), 0) as total_used,
                    COUNT(*) as active_subs,
                    AVG(storage_used_gb) as avg_used
                FROM subscriptions 
                WHERE is_active = TRUE
            ''')
            
            # Top users by storage usage
            top_users = await conn.fetch('''
                SELECT u.user_id, u.username, s.storage_used_gb, s.storage_limit_gb,
                       (s.storage_used_gb / s.storage_limit_gb * 100) as usage_percent
                FROM users u
                JOIN subscriptions s ON u.user_id = s.user_id
                WHERE s.is_active = TRUE
                ORDER BY s.storage_used_gb DESC
                LIMIT 10
            ''')
        
        if not stats:
            await message.answer("📭 No active subscriptions found.")
            return
        
        usage_percent = (stats['total_used'] / stats['total_limit'] * 100) if stats['total_limit'] > 0 else 0
        
        overview_text = (
            "💾 *Storage Overview*\n\n"
            f"📊 *Total Statistics:*\n"
            f"• Active Subscriptions: {stats['active_subs']}\n"
            f"• Total Storage Limit: {stats['total_limit']:.2f} GB\n"
            f"• Total Storage Used: {stats['total_used']:.2f} GB\n"
            f"• Average Usage: {stats['avg_used']:.2f} GB/user\n"
            f"• Overall Usage: {usage_percent:.1f}%\n\n"
            
            f"🏆 *Top 10 Users by Storage Usage:*\n"
        )
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        
        for i, user in enumerate(top_users, 1):
            username = user['username'] or str(user['user_id'])
            overview_text += (
                f"{i}. @{username[:15]} - "
                f"{user['storage_used_gb']:.2f} GB / {user['storage_limit_gb']} GB "
                f"({user['usage_percent']:.1f}%)\n"
            )
            
            keyboard.add(InlineKeyboardButton(
                f"👤 {username[:10]}",
                callback_data=f"user_detail_{user['user_id']}"
            ))
        
        keyboard.row(
            InlineKeyboardButton("📈 Detailed Stats", callback_data="storage_detailed"),
            InlineKeyboardButton("🔄 Refresh", callback_data="admin_storage")
        )
        
        await message.answer(overview_text, reply_markup=keyboard, parse_mode="Markdown")
    
    async def process_add_storage(self, message: types.Message, state: FSMContext):
        """Process adding extra storage to user"""
        try:
            async with state.proxy() as data:
                user_id = data['user_id']
            
            # Parse storage amount
            storage_gb = float(message.text)
            
            async with self.db.pool.acquire() as conn:
                # Get current storage
                current = await conn.fetchrow('''
                    SELECT storage_limit_gb, storage_used_gb
                    FROM subscriptions 
                    WHERE user_id = $1 AND is_active = TRUE
                ''', user_id)
                
                if not current:
                    await message.answer("❌ User doesn't have an active subscription.")
                    await state.finish()
                    return
                
                # Update storage limit
                new_limit = current['storage_limit_gb'] + storage_gb
                await conn.execute('''
                    UPDATE subscriptions 
                    SET storage_limit_gb = $1
                    WHERE user_id = $2 AND is_active = TRUE
                ''', new_limit, user_id)
                
                # Log the action
                await conn.execute('''
                    INSERT INTO admin_logs (admin_id, action, target_user_id, details)
                    VALUES ($1, 'add_storage', $2, $3)
                ''', message.from_user.id, user_id, f"Added {storage_gb} GB storage")
                
                # Get username
                user = await conn.fetchrow(
                    "SELECT username FROM users WHERE user_id = $1",
                    user_id
                )
            
            # Notify user
            try:
                await self.bot.send_message(
                    user_id,
                    f"💾 *Storage Increased!*\n\n"
                    f"Your storage limit has been increased by {storage_gb} GB.\n"
                    f"New limit: {new_limit} GB",
                    parse_mode="Markdown"
                )
            except:
                pass
            
            username = user['username'] or str(user_id)
            await message.answer(f"✅ Added {storage_gb} GB storage to @{username}")
            
        except ValueError:
            await message.answer("❌ Please enter a valid number (e.g., 5.0)")
            return
        
        await state.finish()
    
    # ==================== BROADCAST SYSTEM ====================
    
    async def broadcast_command(self, message: types.Message, state: FSMContext):
        """Command: /broadcast - Send broadcast message"""
        await self.initiate_broadcast(message, state)
    
    async def initiate_broadcast(self, message: types.Message, state: FSMContext):
        """Start broadcast message creation"""
        await AdminStates.SEND_BROADCAST.set()
        await message.answer(
            "📢 *Create Broadcast Message*\n\n"
            "Please send the message you want to broadcast.\n"
            "You can include text, images, videos, or documents.\n\n"
            "Type /cancel to abort.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
    
    async def handle_broadcast_message(self, message: types.Message, state: FSMContext):
        """Handle broadcast message input"""
        # Save message data
        async with state.proxy() as data:
            data['broadcast_message'] = message.text or message.caption
            data['content_type'] = message.content_type
            data['message_id'] = message.message_id
            data['chat_id'] = message.chat.id
        
        # Get user count for confirmation
        async with self.db.pool.acquire() as conn:
            user_count = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE is_approved = TRUE AND is_banned = FALSE"
            )
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("✅ Send Now", callback_data="broadcast_confirm_now"),
            InlineKeyboardButton("📅 Schedule", callback_data="broadcast_confirm_schedule"),
            InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")
        )
        
        preview_text = (
            "📢 *Broadcast Preview*\n\n"
            f"Message: {message.text or message.caption or 'Media file'}\n"
            f"Type: {message.content_type}\n"
            f"Recipients: {user_count} users\n\n"
            "Select an option:"
        )
        
        await AdminStates.SEND_BROADCAST_CONFIRM.set()
        await message.answer(preview_text, reply_markup=keyboard, parse_mode="Markdown")
    
    async def confirm_broadcast(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Confirm and send broadcast"""
        action = callback_query.data.replace("broadcast_confirm_", "")
        
        if action == "cancel":
            await state.finish()
            await callback_query.message.answer("❌ Broadcast cancelled.")
            await callback_query.answer()
            return
        
        async with state.proxy() as data:
            message_text = data.get('broadcast_message', '')
            content_type = data['content_type']
            original_message_id = data['message_id']
            original_chat_id = data['chat_id']
        
        # Get approved users
        async with self.db.pool.acquire() as conn:
            users = await conn.fetch(
                "SELECT user_id FROM users WHERE is_approved = TRUE AND is_banned = FALSE"
            )
        
        total_users = len(users)
        successful = 0
        failed = 0
        
        await callback_query.message.edit_text(
            f"📤 Sending broadcast to {total_users} users...\n"
            f"✅ Successful: 0\n"
            f"❌ Failed: 0"
        )
        
        # Send to each user
        for user in users:
            try:
                # Forward or copy the message
                if content_type == 'text':
                    await self.bot.send_message(
                        user['user_id'],
                        message_text,
                        parse_mode="Markdown"
                    )
                else:
                    # For media messages, forward the original
                    await self.bot.copy_message(
                        chat_id=user['user_id'],
                        from_chat_id=original_chat_id,
                        message_id=original_message_id,
                        caption=message_text
                    )
                successful += 1
            except (BotBlocked, ChatNotFound):
                failed += 1
            except Exception as e:
                logger.error(f"Failed to send to {user['user_id']}: {e}")
                failed += 1
            
            # Update progress every 10 users
            if successful % 10 == 0 or failed % 10 == 0:
                try:
                    await callback_query.message.edit_text(
                        f"📤 Sending broadcast to {total_users} users...\n"
                        f"✅ Successful: {successful}\n"
                        f"❌ Failed: {failed}"
                    )
                except:
                    pass
        
        # Final report
        report_text = (
            f"📢 *Broadcast Complete!*\n\n"
            f"✅ Successful: {successful}\n"
            f"❌ Failed: {failed}\n"
            f"📊 Success Rate: {(successful/total_users*100):.1f}%"
        )
        
        await callback_query.message.edit_text(report_text, parse_mode="Markdown")
        await state.finish()
        
        # Log the broadcast
        async with self.db.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO admin_logs (admin_id, action, details)
                VALUES ($1, 'broadcast', $2)
            ''', callback_query.from_user.id, 
               f"Sent to {successful}/{total_users} users")
    
    async def cancel_broadcast(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Cancel broadcast"""
        await state.finish()
        await callback_query.message.edit_text("❌ Broadcast cancelled.")
        await callback_query.answer()
    
    # ==================== STATISTICS & ANALYTICS ====================
    
    async def stats_command(self, message: types.Message):
        """Command: /stats - Show statistics"""
        await self.show_detailed_statistics(message)
    
    async def show_detailed_statistics(self, message: types.Message):
        """Display detailed system statistics"""
        async with self.db.pool.acquire() as conn:
            # User statistics
            user_stats = await conn.fetchrow('''
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE is_approved = TRUE) as approved,
                    COUNT(*) FILTER (WHERE is_banned = TRUE) as banned,
                    COUNT(*) FILTER (WHERE is_admin = TRUE) as admins,
                    COUNT(*) FILTER (WHERE last_active > NOW() - INTERVAL '1 day') as active_today,
                    COUNT(*) FILTER (WHERE last_active > NOW() - INTERVAL '7 days') as active_week,
                    AVG(EXTRACT(EPOCH FROM (NOW() - join_date))/86400)::INTEGER as avg_age_days
                FROM users
            ''')
            
            # Subscription statistics
            sub_stats = await conn.fetchrow('''
                SELECT 
                    COUNT(*) as total_active,
                    SUM(storage_limit_gb) as total_limit,
                    SUM(storage_used_gb) as total_used,
                    COUNT(*) FILTER (WHERE plan_type = 'monthly') as monthly,
                    COUNT(*) FILTER (WHERE plan_type = 'quarterly') as quarterly,
                    COUNT(*) FILTER (WHERE plan_type = 'half_year') as half_year,
                    COUNT(*) FILTER (WHERE plan_type = 'yearly') as yearly
                FROM subscriptions 
                WHERE is_active = TRUE
            ''')
            
            # File statistics
            file_stats = await conn.fetchrow('''
                SELECT 
                    COUNT(*) as total_files,
                    COALESCE(SUM(file_size), 0) as total_size_bytes,
                    COUNT(*) FILTER (WHERE file_type = 'document') as documents,
                    COUNT(*) FILTER (WHERE file_type = 'photo') as photos,
                    COUNT(*) FILTER (WHERE file_type = 'video') as videos,
                    COUNT(*) FILTER (WHERE file_type = 'audio') as audio,
                    COUNT(*) FILTER (WHERE is_shared = TRUE) as shared
                FROM files
            ''')
            
            # Growth statistics (last 30 days)
            growth = await conn.fetchrow('''
                SELECT 
                    COUNT(*) FILTER (WHERE join_date > NOW() - INTERVAL '30 days') as new_users_30d,
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') as new_files_30d
                FROM (SELECT join_date FROM users) u,
                     (SELECT created_at FROM files) f
            ''')
        
        # Convert bytes to GB
        total_size_gb = file_stats['total_size_bytes'] / (1024**3)
        
        stats_text = (
            "📈 *System Statistics*\n\n"
            
            "👥 *User Statistics:*\n"
            f"• Total Users: {user_stats['total']}\n"
            f"• Approved: {user_stats['approved']}\n"
            f"• Banned: {user_stats['banned']}\n"
            f"• Admins: {user_stats['admins']}\n"
            f"• Active Today: {user_stats['active_today']}\n"
            f"• Active This Week: {user_stats['active_week']}\n"
            f"• Average Account Age: {user_stats['avg_age_days']} days\n"
            f"• New Users (30d): {growth['new_users_30d']}\n\n"
            
            "💰 *Subscription Statistics:*\n"
            f"• Active Subscriptions: {sub_stats['total_active']}\n"
            f"• Monthly Plans: {sub_stats['monthly']}\n"
            f"• Quarterly Plans: {sub_stats['quarterly']}\n"
            f"• Half-Year Plans: {sub_stats['half_year']}\n"
            f"• Yearly Plans: {sub_stats['yearly']}\n"
            f"• Total Storage Limit: {sub_stats['total_limit']:.2f} GB\n"
            f"• Total Storage Used: {sub_stats['total_used']:.2f} GB\n"
            f"• Usage Percentage: {(sub_stats['total_used']/sub_stats['total_limit']*100 if sub_stats['total_limit'] > 0 else 0):.1f}%\n\n"
            
            "📁 *File Statistics:*\n"
            f"• Total Files: {file_stats['total_files']}\n"
            f"• Total Size: {total_size_gb:.2f} GB\n"
            f"• Documents: {file_stats['documents']}\n"
            f"• Photos: {file_stats['photos']}\n"
            f"• Videos: {file_stats['videos']}\n"
            f"• Audio: {file_stats['audio']}\n"
            f"• Shared Files: {file_stats['shared']}\n"
            f"• New Files (30d): {growth['new_files_30d']}\n"
        )
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("📊 Export CSV", callback_data="export_stats_csv"),
            InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")
        )
        
        await message.answer(stats_text, reply_markup=keyboard, parse_mode="Markdown")
    
    # ==================== REVENUE MANAGEMENT ====================
    
    async def revenue_command(self, message: types.Message):
        """Command: /revenue - Show revenue statistics"""
        await self.show_revenue_stats(message)
    
    async def show_revenue_stats(self, message: types.Message):
        """Display revenue statistics"""
        async with self.db.pool.acquire() as conn:
            # Revenue by plan type
            revenue = await conn.fetchrow('''
                SELECT 
                    SUM(CASE WHEN plan_type = 'monthly' THEN amount ELSE 0 END) as monthly,
                    SUM(CASE WHEN plan_type = 'quarterly' THEN amount ELSE 0 END) as quarterly,
                    SUM(CASE WHEN plan_type = 'half_year' THEN amount ELSE 0 END) as half_year,
                    SUM(CASE WHEN plan_type = 'yearly' THEN amount ELSE 0 END) as yearly,
                    SUM(amount) as total,
                    COUNT(*) as total_transactions
                FROM payment_tickets 
                WHERE status = 'completed'
            ''')
            
            # Monthly revenue (last 6 months)
            monthly_revenue = await conn.fetch('''
                SELECT 
                    DATE_TRUNC('month', created_at) as month,
                    SUM(amount) as revenue,
                    COUNT(*) as transactions
                FROM payment_tickets 
                WHERE status = 'completed'
                AND created_at > NOW() - INTERVAL '6 months'
                GROUP BY DATE_TRUNC('month', created_at)
                ORDER BY month DESC
            ''')
            
            # Today's revenue
            today_revenue = await conn.fetchrow('''
                SELECT SUM(amount) as revenue, COUNT(*) as transactions
                FROM payment_tickets 
                WHERE status = 'completed'
                AND DATE(created_at) = CURRENT_DATE
            ''')
        
        revenue_text = (
            "💰 *Revenue Statistics*\n\n"
            
            "📅 *Total Revenue:*\n"
            f"• Monthly Plans: ₹{revenue['monthly'] or 0:.2f}\n"
            f"• Quarterly Plans: ₹{revenue['quarterly'] or 0:.2f}\n"
            f"• Half-Year Plans: ₹{revenue['half_year'] or 0:.2f}\n"
            f"• Yearly Plans: ₹{revenue['yearly'] or 0:.2f}\n"
            f"• **Total:** ₹{revenue['total'] or 0:.2f}\n"
            f"• Transactions: {revenue['total_transactions']}\n\n"
            
            "📊 *Today's Revenue:*\n"
            f"• Revenue: ₹{today_revenue['revenue'] or 0:.2f}\n"
            f"• Transactions: {today_revenue['transactions'] or 0}\n\n"
            
            "📈 *Last 6 Months:*\n"
        )
        
        for month_data in monthly_revenue:
            month = month_data['month'].strftime('%b %Y')
            revenue_text += f"• {month}: ₹{month_data['revenue']:.2f} ({month_data['transactions']} txn)\n"
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("📊 Export Report", callback_data="export_revenue_csv"),
            InlineKeyboardButton("💳 Payment Methods", callback_data="payment_methods"),
            InlineKeyboardButton("🔄 Refresh", callback_data="admin_revenue")
        )
        
        await message.answer(revenue_text, reply_markup=keyboard, parse_mode="Markdown")
    
    # ==================== SEARCH FUNCTIONALITY ====================
    
    async def search_command(self, message: types.Message, state: FSMContext):
        """Command: /search - Search for users"""
        args = message.get_args()
        if args:
            await self.search_users(message, args)
        else:
            await self.search_user_prompt(message, state)
    
    async def search_user_prompt(self, message: types.Message, state: FSMContext):
        """Prompt for search query"""
        await AdminStates.SEARCH_USER.set()
        await message.answer(
            "🔍 *Search Users*\n\n"
            "Enter username, user ID, or name to search:\n"
            "Type /cancel to abort.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
    
    async def process_user_search(self, message: types.Message, state: FSMContext):
        """Process user search query"""
        query = message.text.strip()
        
        async with self.db.pool.acquire() as conn:
            # Search by different criteria
            users = await conn.fetch('''
                SELECT user_id, username, first_name, last_name, 
                       is_approved, is_banned, join_date
                FROM users 
                WHERE user_id::TEXT LIKE $1 OR 
                      username ILIKE $1 OR 
                      first_name ILIKE $1 OR 
                      last_name ILIKE $1
                ORDER BY join_date DESC
                LIMIT 20
            ''', f"%{query}%")
        
        if not users:
            await message.answer("❌ No users found matching your query.")
            await state.finish()
            return
        
        keyboard = InlineKeyboardMarkup(row_width=1)
        
        for user in users:
            status = "✅" if user['is_approved'] else "⏳"
            status = "🚫" if user['is_banned'] else status
            username = user['username'] or f"{user['first_name']} {user['last_name'] or ''}"
            
            keyboard.add(InlineKeyboardButton(
                f"{status} {username[:20]} (ID: {user['user_id']})",
                callback_data=f"user_detail_{user['user_id']}"
            ))
        
        keyboard.add(InlineKeyboardButton("🔙 Back to Search", callback_data="admin_search"))
        
        await message.answer(
            f"🔍 *Search Results for '{query}'*\n\n"
            f"Found {len(users)} user(s):",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await state.finish()
    
    async def search_users(self, message: types.Message, query: str):
        """Search users directly"""
        async with self.db.pool.acquire() as conn:
            users = await conn.fetch('''
                SELECT user_id, username, first_name, last_name, 
                       is_approved, is_banned, join_date
                FROM users 
                WHERE user_id::TEXT LIKE $1 OR 
                      username ILIKE $1 OR 
                      first_name ILIKE $1 OR 
                      last_name ILIKE $1
                ORDER BY join_date DESC
                LIMIT 10
            ''', f"%{query}%")
        
        if not users:
            await message.answer("❌ No users found.")
            return
        
        response = f"🔍 *Search Results for '{query}'*\n\n"
        
        for user in users:
            status = "✅" if user['is_approved'] else "⏳"
            status = "🚫" if user['is_banned'] else status
            username = user['username'] or f"{user['first_name']} {user['last_name'] or ''}"
            response += f"{status} {username} (ID: `{user['user_id']}`)\n"
        
        await message.answer(response, parse_mode="Markdown")
    
    # ==================== BACKUP & EXPORT ====================
    
    async def backup_command(self, message: types.Message):
        """Command: /backup - Create system backup"""
        await self.create_backup(message)
    
    async def create_backup(self, message: types.Message):
        """Create and send system backup"""
        try:
            # Create backup data
            backup_data = await self.generate_backup_data()
            
            # Create Excel file
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                for sheet_name, data in backup_data.items():
                    if data:
                        df = pd.DataFrame(data)
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            output.seek(0)
            
            # Send backup file
            await message.answer_document(
                InputFile(output, filename=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"),
                caption="📦 *System Backup*\n\nDatabase backup created successfully.",
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Backup creation failed: {e}")
            await message.answer(f"❌ Backup creation failed: {str(e)}")
    
    async def generate_backup_data(self) -> Dict:
        """Generate backup data from database"""
        async with self.db.pool.acquire() as conn:
            # Get all tables data
            tables = {
                'users': await conn.fetch("SELECT * FROM users"),
                'subscriptions': await conn.fetch("SELECT * FROM subscriptions"),
                'files': await conn.fetch("SELECT * FROM files"),
                'payment_tickets': await conn.fetch("SELECT * FROM payment_tickets"),
                'admin_logs': await conn.fetch("SELECT * FROM admin_logs")
            }
        
        # Convert to list of dicts
        backup_data = {}
        for table_name, records in tables.items():
            backup_data[table_name] = [dict(record) for record in records]
        
        return backup_data
    
    async def export_users_csv(self, message: types.Message):
        """Export users to CSV"""
        try:
            async with self.db.pool.acquire() as conn:
                users = await conn.fetch('''
                    SELECT user_id, username, first_name, last_name,
                           profile_link, is_approved, is_banned, is_admin,
                           join_date, last_active
                    FROM users
                    ORDER BY join_date DESC
                ''')
            
            # Create DataFrame
            df = pd.DataFrame([dict(user) for user in users])
            output = BytesIO()
            df.to_csv(output, index=False)
            output.seek(0)
            
            await message.answer_document(
                InputFile(output, filename=f"users_export_{datetime.now().strftime('%Y%m%d')}.csv"),
                caption="📊 Users Export",
                parse_mode="Markdown"
            )
            
        except Exception as e:
            logger.error(f"Export failed: {e}")
            await message.answer(f"❌ Export failed: {str(e)}")
    
    # ==================== SETTINGS & UTILITIES ====================
    
    async def show_settings(self, message: types.Message):
        """Display admin settings"""
        keyboard = InlineKeyboardMarkup(row_width=2)
        
        buttons = [
            InlineKeyboardButton("🔑 Change Secret Code", callback_data="change_secret"),
            InlineKeyboardButton("📊 System Info", callback_data="system_info"),
            InlineKeyboardButton("🧹 Cleanup Database", callback_data="db_cleanup"),
            InlineKeyboardButton("🚫 Maintenance Mode", callback_data="maintenance"),
            InlineKeyboardButton("🔔 Notifications", callback_data="notifications"),
            InlineKeyboardButton("📋 Log Settings", callback_data="log_settings"),
        ]
        
        for i in range(0, len(buttons), 2):
            if i+1 < len(buttons):
                keyboard.add(buttons[i], buttons[i+1])
            else:
                keyboard.add(buttons[i])
        
        await message.answer(
            "⚙️ *Admin Settings*\n\n"
            "Configure system settings:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    
    async def show_system_info(self, message: types.Message):
        """Display system information"""
        import psutil
        import platform
        
        # System info
        system_info = (
            f"🖥️ *System Information*\n\n"
            f"• Python: {platform.python_version()}\n"
            f"• OS: {platform.system()} {platform.release()}\n"
            f"• Processor: {platform.processor()}\n"
            f"• Bot Uptime: {self.get_uptime()}\n\n"
        )
        
        # Memory usage
        memory = psutil.virtual_memory()
        system_info += (
            f"💾 *Memory Usage*\n"
            f"• Total: {memory.total / (1024**3):.2f} GB\n"
            f"• Used: {memory.used / (1024**3):.2f} GB\n"
            f"• Free: {memory.available / (1024**3):.2f} GB\n"
            f"• Usage: {memory.percent}%\n\n"
        )
        
        # Database info
        async with self.db.pool.acquire() as conn:
            db_size = await conn.fetchval(
                "SELECT pg_database_size(current_database())"
            )
            
            system_info += (
                f"🗄️ *Database*\n"
                f"• Size: {db_size / (1024**2):.2f} MB\n"
            )
        
        await message.answer(system_info, parse_mode="Markdown")
    
    async def show_recent_logs(self, message: types.Message, limit: int = 20):
        """Show recent admin logs"""
        async with self.db.pool.acquire() as conn:
            logs = await conn.fetch('''
                SELECT l.*, u.username as admin_username
                FROM admin_logs l
                LEFT JOIN users u ON l.admin_id = u.user_id
                ORDER BY timestamp DESC
                LIMIT $1
            ''', limit)
        
        if not logs:
            await message.answer("📭 No logs found.")
            return
        
        logs_text = "📋 *Recent Admin Logs*\n\n"
        
        for log in logs:
            admin_name = log['admin_username'] or f"ID:{log['admin_id']}"
            timestamp = log['timestamp'].strftime('%Y-%m-%d %H:%M')
            
            logs_text += (
                f"⏰ {timestamp}\n"
                f"👤 {admin_name}\n"
                f"📝 {log['action']}\n"
            )
            
            if log['target_user_id']:
                logs_text += f"🎯 Target: {log['target_user_id']}\n"
            
            if log['details']:
                logs_text += f"📄 {log['details'][:50]}...\n"
            
            logs_text += "─" * 20 + "\n"
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔄 Refresh", callback_data="admin_logs"))
        
        await message.answer(logs_text, reply_markup=keyboard, parse_mode="Markdown")
    
    # ==================== HELPER METHODS ====================
    
    def get_uptime(self) -> str:
        """Calculate bot uptime"""
        # This should be initialized when bot starts
        # For now, return placeholder
        return "Not tracked"
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id == self.admin_id
    
    async def log_admin_action(self, admin_id: int, action: str, target_user_id: int = None, details: str = ""):
        """Log admin action to database"""
        async with self.db.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO admin_logs (admin_id, action, target_user_id, details)
                VALUES ($1, $2, $3, $4)
            ''', admin_id, action, target_user_id, details)