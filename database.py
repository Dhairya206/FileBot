from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

class DatabaseManager:
    def __init__(self, db_name="yt_downloader", collection_name="downloads"):
        """
        Initializes the connection to MongoDB.
        """
        # Default connection string for a local MongoDB instance
        self.client = MongoClient("mongodb://localhost:27017/")
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]

    def check_connection(self):
        """Verifies if the database is accessible."""
        try:
            self.client.admin.command('ping')
            print("Successfully connected to MongoDB.")
            return True
        except ConnectionFailure:
            print("MongoDB connection failed. Make sure the service is running.")
            return False

    def save_video_metadata(self, video_data):
        """
        Inserts video info into the database.
        Expected video_data format: {'title': str, 'url': str, 'status': str}
        """
        try:
            result = self.collection.insert_one(video_data)
            print(f"Metadata saved with ID: {result.inserted_id}")
            return result.inserted_id
        except Exception as e:
            print(f"Error saving to database: {e}")
            return None

    def is_already_downloaded(self, video_url):
        """Checks if a URL already exists in our collection."""
        return self.collection.find_one({"url": video_url}) is not None

# Example Usage:
if __name__ == "__main__":
    db = DatabaseManager()
    if db.check_connection():
        sample_data = {
            "title": "My First Download",
            "url": "https://youtube.com/watch?v=example",
            "status": "completed"
        }
        db.save_video_metadata(sample_data)
