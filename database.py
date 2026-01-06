import pymongo
from pymongo import MongoClient

class YTDatabase:
    def __init__(self, uri="mongodb://localhost:27017/"):
        """Initializes connection to the MongoDB instance."""
        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=2000)
            self.db = self.client["youtube_downloader"]
            self.collection = self.db["video_history"]
            # Trigger a connection check
            self.client.server_info() 
        except Exception as e:
            print(f"Database Connection Error: {e}")

    def add_video(self, video_details):
        """
        Adds a video record to the database.
        video_details should be a dict: {'title': str, 'url': str, 'file_path': str}
        """
        try:
            result = self.collection.insert_one(video_details)
            print(f"Successfully logged to DB. ID: {result.inserted_id}")
        except Exception as e:
            print(f"Failed to save to DB: {e}")

    def get_all_downloads(self):
        """Returns all downloaded video records."""
        return list(self.collection.find({}, {"_id": 0}))

# To use this in your other files:
# from database import YTDatabase
# db = YTDatabase()
