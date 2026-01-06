def admin_broadcast(update, context):
    msg = " ".join(context.args)
    # Logic to send msg to all users from database
    update.message.reply_text(f"Broadcasting: {msg}")
