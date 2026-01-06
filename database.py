import pymongo

# MongoDB connection (UserLAnd mein local ya MongoDB Atlas use karein)
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["railway_bot"]
tickets_col = db["tickets"]

def save_ticket(user_id, issue):
    ticket_data = {"user_id": user_id, "issue": issue, "status": "Open"}
    result = tickets_col.insert_one(ticket_data)
    return result.inserted_id

def get_all_tickets():
    return list(tickets_col.find())
