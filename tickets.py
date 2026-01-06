from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

ADMIN_ID = 7960003520 # Change to your ID

async def create_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text("🎫 Ticket Open! Admin @dhairya_hu will add you to a group soon.")
    
    # Notify Admin
    msg = f"New Ticket: {user.first_name} (@{user.username})\nID: {user.id}"
    btn = [[InlineKeyboardButton("✅ Close Ticket", callback_data=f"close_{user.id}")]]
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg, reply_markup=InlineKeyboardMarkup(btn))

async def close_ticket_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.data.split("_")[1]
    await query.answer()
    await query.edit_message_text(f"Ticket for {uid} closed.")
