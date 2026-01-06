import logging

# Logging setup taaki errors terminal mein dikhein
logging.basicConfig(level=logging.INFO)

try:
    import pymongo
    # Connection setup
    # Agar aapka MongoDB local hai toh localhost use karein, 
    # varna apni MongoDB Atlas URI yahan dalein
    client = pymongo.MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
    db = client["railway_bot"]
    tickets_col = db["tickets"]
    MONGO_AVAILABLE = True
    logging.info("Database connected successfully!")
except (ImportError, Exception) as e:
    MONGO_AVAILABLE = False
    logging.warning(f"Database NOT connected: {e}. Bot will run without DB.")

def save_ticket(user_id, issue):
    if not MONGO_AVAILABLE:
        return "Offline_Mode_No_DB"
    
    ticket_data = {"user_id": user_id, "issue": issue, "status": "Open"}
    try:
        result = tickets_col.insert_one(ticket_data)
        return result.inserted_id
    except Exception:
        return "Error_Saving_Data"

def get_all_tickets():
    if not MONGO_AVAILABLE:
        return []
    return list(tickets_col.find())
