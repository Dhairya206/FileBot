import pymongo
from pymongo import MongoClient

class YTDatabase:
    def __init__(self, uri="mongodb://localhost:27017/"):
        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=2000)
            self.db = self.client["youtube_downloader"]
            self.collection = self.db["video_history"]
        except Exception as e:
            print(f"Database Error: {e}")

    def add_video(self, video_details):
        return self.collection.insert_one(video_details)

    def is_downloaded(self, url):
        return self.collection.find_one({"url": url}) is not None
