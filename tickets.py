import database

def handle_ticket_creation(update, context):
    user_id = update.message.from_user.id
    # Ticket ka text extract karna: /ticket My train is late
    issue_text = " ".join(context.args)
    
    if not issue_text:
        update.message.reply_text("Please describe your issue. Example: /ticket My issue...")
        return

    ticket_id = database.save_ticket(user_id, issue_text)
    update.message.reply_text(f"Ticket Created! ID: {ticket_id}\nOur team will contact you.")

def view_tickets(update, context):
    # Sirf admin ya user apne tickets dekh sakein
    all_tickets = database.get_all_tickets()
    response = "Current Tickets:\n"
    for t in all_tickets:
        response += f"ID: {t['_id']} | Status: {t['status']}\n"
    update.message.reply_text(response)
