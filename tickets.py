import os
import logging
import asyncio
import hashlib
import qrcode
import io
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ChatAction
from database import Database

logger = logging.getLogger(__name__)
db = Database()

ADMIN_ID = int(os.getenv('ADMIN_ID'))
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Plan prices in INR
PLAN_PRICES = {
    'monthly': 25,
    'quarterly': 60,
    'semiannual': 125,
    'yearly': 275
}

# Plan storage limits in bytes
PLAN_STORAGE = {
    'monthly': 5 * 1024 * 1024 * 1024,  # 5GB
    'quarterly': 15 * 1024 * 1024 * 1024,  # 15GB
    'semiannual': 30 * 1024 * 1024 * 1024,  # 30GB
    'yearly': 100 * 1024 * 1024 * 1024  # 100GB
}

async def create_ticket_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ticket command - create payment ticket"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data or not user_data['is_approved']:
        await update.message.reply_text(
            "❌ **Access Denied**\n\n"
            "You must be an approved user to create payment tickets.\n"
            "Please complete registration and wait for admin approval.",
            parse_mode='Markdown'
        )
        return
    
    # Check if user already has an open ticket
    open_tickets = db.get_user_tickets(user_data['id'], status='open')
    if open_tickets:
        ticket = open_tickets[0]
        await update.message.reply_text(
            f"⚠️ **You already have an open ticket**\n\n"
            f"Ticket ID: `{ticket['id']}`\n"
            f"Plan: {ticket['plan_type'] or 'Not specified'}\n"
            f"Amount: ₹{ticket['amount'] or 'Not specified'}\n\n"
            f"Please wait for admin to process this ticket.\n"
            f"If you need to create a new ticket, ask admin to close the current one.",
            parse_mode='Markdown'
        )
        return
    
    # Show plan selection
    keyboard = [
        [InlineKeyboardButton("💰 Monthly - ₹25", callback_data="ticket_monthly")],
        [InlineKeyboardButton("💰 Quarterly - ₹60", callback_data="ticket_quarterly")],
        [InlineKeyboardButton("💰 Semi-Annual - ₹125", callback_data="ticket_semiannual")],
        [InlineKeyboardButton("💰 Annual - ₹275", callback_data="ticket_yearly")],
        [InlineKeyboardButton("❌ Cancel", callback_data="ticket_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎫 **Create Payment Ticket**\n\n"
        "Select a subscription plan:\n\n"
        "1. **Monthly** - ₹25 (5GB storage)\n"
        "2. **Quarterly** - ₹60 (15GB storage)\n"
        "3. **Semi-Annual** - ₹125 (30GB storage)\n"
        "4. **Annual** - ₹275 (100GB storage)\n\n"
        "After selection, a private payment group will be created.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def create_ticket_for_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, plan_type: str):
    """Create ticket for specific plan"""
    user_data = db.get_user_by_id(user_id)
    if not user_data:
        return
    
    amount = PLAN_PRICES.get(plan_type, 0)
    
    # Create ticket in database
    ticket_id = db.create_ticket(
        user_id=user_id,
        ticket_type='payment',
        plan_type=plan_type,
        amount=amount
    )
    
    if not ticket_id:
        await update.message.reply_text("❌ Failed to create ticket. Please try again.")
        return
    
    # Create private Telegram group for payment
    try:
        bot = context.bot
        group_title = f"Payment Ticket #{ticket_id}"
        group_description = f"Payment ticket for @{user_data['username']} - {plan_type} plan"
        
        # Create the group (initially with bot as only member)
        chat = await bot.create_group_chat(
            title=group_title,
            user_ids=[]
        )
        group_id = chat.id
        
        # Set group description
        await bot.set_chat_description(chat_id=group_id, description=group_description)
        
        # Update ticket with group ID
        db.update_ticket_group(ticket_id, group_id)
        
        # Notify user
        await update.message.reply_text(
            f"✅ **Ticket Created Successfully**\n\n"
            f"🆔 Ticket ID: `{ticket_id}`\n"
            f"📋 Plan: {plan_type}\n"
            f"💰 Amount: ₹{amount}\n"
            f"👤 Username: @{user_data['username']}\n\n"
            f"A private payment group has been created.\n"
            f"Admin will add you to the group shortly.\n\n"
            f"You can also pay via QR code using /pay_via_qr",
            parse_mode='Markdown'
        )
        
        # Notify admin
        admin_message = (
            f"🎫 **New Payment Ticket**\n\n"
            f"🆔 Ticket ID: `{ticket_id}`\n"
            f"👤 User: @{user_data['username']}\n"
            f"📋 Plan: {plan_type}\n"
            f"💰 Amount: ₹{amount}\n"
            f"💬 Group ID: `{group_id}`\n\n"
            f"**Commands:**\n"
            f"• Use `/addtogroup {ticket_id}` to add user to payment group\n"
            f"• Use `/closeticket {ticket_id}` to close ticket\n"
            f"• Use `/adduser @{user_data['username']} {plan_type}` to activate subscription\n"
        )
        
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Failed to create payment group: {e}")
        await update.message.reply_text(
            f"✅ Ticket created (ID: `{ticket_id}`)\n"
            f"⚠️ Could not create payment group. Admin will contact you directly.",
            parse_mode='Markdown'
        )

async def pay_via_qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pay_via_qr command - generate QR code for payment"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data or not user_data['is_approved']:
        await update.message.reply_text(
            "❌ You must be an approved user to use this feature."
        )
        return
    
    # Check for open ticket
    open_tickets = db.get_user_tickets(user_data['id'], status='open')
    if not open_tickets:
        await update.message.reply_text(
            "❌ You don't have any open payment tickets.\n"
            "Please create a ticket first using /ticket"
        )
        return
    
    ticket = open_tickets[0]
    amount = ticket['amount'] or PLAN_PRICES.get(ticket['plan_type'], 0)
    
    # Generate QR code data
    qr_data = generate_qr_data(ticket['id'], user_data['username'], amount)
    
    # Update ticket with QR code data
    db.update_ticket_qr_code(ticket['id'], qr_data)
    
    # Generate QR code image
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    
    # Create image
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to bytes
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    # Send QR code to user
    await update.message.reply_photo(
        photo=img_byte_arr,
        caption=f"💰 **Payment QR Code**\n\n"
               f"🆔 Ticket ID: `{ticket['id']}`\n"
               f"👤 User: @{user_data['username']}\n"
               f"📋 Plan: {ticket['plan_type']}\n"
               f"💰 Amount: ₹{amount}\n\n"
               f"**Instructions:**\n"
               f"1. Scan this QR code with any UPI app\n"
               f"2. Complete the payment\n"
               f"3. Send screenshot to admin in the payment group\n"
               f"4. Wait for verification\n\n"
               f"QR Data: `{qr_data[:50]}...`",
        parse_mode='Markdown'
    )
    
    # Instructions for offline payment
    await update.message.reply_text(
        "💳 **Offline Payment Option**\n\n"
        "If you prefer offline payment:\n\n"
        "1. Contact admin for bank details\n"
        "2. Make payment via bank transfer/UPI\n"
        "3. Get a redeem code from admin\n"
        "4. Provide redeem code in payment group\n\n"
        "Admin will verify and activate your subscription.",
        parse_mode='Markdown'
    )

def generate_qr_data(ticket_id: str, username: str, amount: float) -> str:
    """Generate QR code data for UPI payment"""
    # This is a simplified UPI QR code format
    # In production, you would use actual UPI merchant details
    
    # Generate a unique transaction reference
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    txn_ref = f"FILEX{ticket_id}{timestamp}"
    
    # UPI QR code format (simplified)
    upi_id = os.getenv('UPI_ID', 'admin@upi')  # Set your UPI ID in environment
    merchant_name = "TheFilex Bot"
    
    qr_data = (
        f"upi://pay?pa={upi_id}"
        f"&pn={merchant_name}"
        f"&tid={txn_ref}"
        f"&tr={txn_ref}"
        f"&tn=Payment for {username} - Ticket {ticket_id}"
        f"&am={amount}"
        f"&cu=INR"
        f"&mode=02"
    )
    
    return qr_data

async def handle_redeem_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle redeem code submission in payment groups"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    
    # Check if this is a payment group
    ticket = None
    try:
        # Find ticket by group ID
        # This would require a database query to find ticket by telegram_group_id
        # For now, we'll assume it's a payment group if message contains "TICKET"
        if "TICKET" in message_text.upper() or "REDEEM" in message_text.upper():
            # Extract ticket ID from message
            words = message_text.split()
            for word in words:
                if len(word) == 10 and word.startswith('ticket'):  # Assuming ticket IDs are like "ticket12345"
                    ticket = db.get_ticket(word)
                    break
    except:
        pass
    
    if ticket and ticket['status'] == 'open':
        # This is a redeem code submission
        redeem_code = message_text.strip()
        
        # Update ticket with redeem code
        db.update_ticket_redeem_code(ticket['id'], redeem_code)
        
        # Notify admin
        user_data = db.get_user_by_id(ticket['user_id'])
        if user_data:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🔑 **Redeem Code Submitted**\n\n"
                     f"🆔 Ticket: `{ticket['id']}`\n"
                     f"👤 User: @{user_data['username']}\n"
                     f"🔐 Code: `{redeem_code}`\n\n"
                     f"Verify the payment and use:\n"
                     f"`/adduser @{user_data['username']} {ticket['plan_type']}`",
                parse_mode='Markdown'
            )
        
        await update.message.reply_text(
            f"✅ Redeem code submitted successfully!\n"
            f"Admin will verify and activate your subscription shortly."
        )

async def add_to_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to add user to payment group"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/addtogroup ticket_id`", parse_mode='Markdown')
        return
    
    ticket_id = context.args[0]
    ticket = db.get_ticket(ticket_id)
    
    if not ticket:
        await update.message.reply_text(f"❌ Ticket {ticket_id} not found.")
        return
    
    if not ticket['telegram_group_id']:
        await update.message.reply_text(f"❌ No group associated with ticket {ticket_id}.")
        return
    
    user_data = db.get_user_by_id(ticket['user_id'])
    if not user_data:
        await update.message.reply_text(f"❌ User not found for ticket {ticket_id}.")
        return
    
    try:
        # Add user to the group
        bot = context.bot
        
        # First, add admin to the group if not already there
        await bot.add_chat_members(
            chat_id=ticket['telegram_group_id'],
            user_ids=[ADMIN_ID]
        )
        
        # Add user to the group
        await bot.add_chat_members(
            chat_id=ticket['telegram_group_id'],
            user_ids=[user_data['telegram_id']]
        )
        
        # Send welcome message in group
        group_message = (
            f"👋 **Welcome to Payment Group**\n\n"
            f"🆔 Ticket ID: `{ticket_id}`\n"
            f"👤 User: @{user_data['username']}\n"
            f"📋 Plan: {ticket['plan_type']}\n"
            f"💰 Amount: ₹{ticket['amount']}\n\n"
            f"**Payment Options:**\n"
            f"1. Use /pay_via_qr in bot DM to get QR code\n"
            f"2. Pay via UPI/Bank transfer and share details\n"
            f"3. Share payment screenshot for verification\n\n"
            f"Admin will verify and activate your subscription."
        )
        
        await bot.send_message(
            chat_id=ticket['telegram_group_id'],
            text=group_message,
            parse_mode='Markdown'
        )
        
        await update.message.reply_text(
            f"✅ User @{user_data['username']} added to payment group.\n"
            f"Group ID: `{ticket['telegram_group_id']}`"
        )
        
    except Exception as e:
        logger.error(f"Error adding user to group: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def ticket_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle ticket-related callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    user_data = db.get_user(user_id)
    
    if not user_data or not user_data['is_approved']:
        await query.edit_message_text("❌ You must be an approved user.")
        return
    
    if data == "ticket_cancel":
        await query.edit_message_text("Ticket creation cancelled.")
        return
    
    # Handle plan selection
    plan_map = {
        "ticket_monthly": "monthly",
        "ticket_quarterly": "quarterly",
        "ticket_semiannual": "semiannual",
        "ticket_yearly": "yearly"
    }
    
    if data in plan_map:
        plan_type = plan_map[data]
        await create_ticket_for_plan(update, context, user_data['id'], plan_type)
        await query.delete_message()

async def view_my_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View user's tickets"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("User not found. Please use /start first.")
        return
    
    tickets = db.get_user_tickets(user_data['id'])
    
    if not tickets:
        await update.message.reply_text("📭 You don't have any tickets.")
        return
    
    tickets_text = "🎫 **Your Tickets**\n\n"
    
    for ticket in tickets:
        status_icon = "🟢" if ticket['status'] == 'open' else "🔴"
        tickets_text += (
            f"{status_icon} **Ticket #{ticket['id']}**\n"
            f"   Type: {ticket['ticket_type']}\n"
            f"   Plan: {ticket['plan_type'] or 'N/A'}\n"
            f"   Amount: ₹{ticket['amount'] or '0'}\n"
            f"   Status: {ticket['status']}\n"
            f"   Created: {ticket['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
            f"   ---\n"
        )
    
    await update.message.reply_text(tickets_text, parse_mode='Markdown')

# Ticket status check command
async def ticket_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check status of a specific ticket"""
    user_id = update.effective_user.id
    user_data = db.get_user(user_id)
    
    if not user_data:
        await update.message.reply_text("User not found. Please use /start first.")
        return
    
    if context.args:
        ticket_id = context.args[0]
        ticket = db.get_ticket(ticket_id)
        
        if not ticket or ticket['user_id'] != user_data['id']:
            await update.message.reply_text("❌ Ticket not found or access denied.")
            return
        
        status_icon = "🟢" if ticket['status'] == 'open' else "🔴"
        
        await update.message.reply_text(
            f"{status_icon} **Ticket #{ticket['id']}**\n\n"
            f"📋 Type: {ticket['ticket_type']}\n"
            f"💰 Plan: {ticket['plan_type'] or 'N/A'}\n"
            f"💸 Amount: ₹{ticket['amount'] or '0'}\n"
            f"📊 Status: {ticket['status']}\n"
            f"📅 Created: {ticket['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
            f"🔒 Group ID: `{ticket['telegram_group_id'] or 'Not assigned'}`\n\n"
            f"Contact admin if you have questions.",
            parse_mode='Markdown'
        )
    else:
        await view_my_tickets(update, context)

def setup_ticket_handlers(application):
    """Setup all ticket-related handlers"""
    
    # Ticket commands
    application.add_handler(CommandHandler("ticket", create_ticket_command))
    application.add_handler(CommandHandler("pay_via_qr", pay_via_qr_command))
    application.add_handler(CommandHandler("mytickets", view_my_tickets))
    application.add_handler(CommandHandler("ticketstatus", ticket_status))
    
    # Admin ticket commands
    application.add_handler(CommandHandler("addtogroup", add_to_group_command))
    
    # Ticket callback handler
    application.add_handler(CallbackQueryHandler(ticket_callback_handler, pattern="^ticket_"))
    
    # Handle redeem code messages in groups (if implemented)
    # application.add_handler(MessageHandler(
    #     filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
    #     handle_redeem_code
    # ))
    
    logger.info("Ticket handlers setup complete")