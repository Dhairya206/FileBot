import psycopg2
import os
from datetime import datetime, timedelta

DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    # Users: stores plan, storage used, and admin expiry
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        plan TEXT DEFAULT 'free',
        expiry_date TIMESTAMP,
        storage_used BIGINT DEFAULT 0,
        storage_limit BIGINT DEFAULT 0,
        is_admin BOOLEAN DEFAULT FALSE,
        admin_expiry TIMESTAMP
    )''')
    # Files: stores the Telegram file_id (Universal Storage)
    cur.execute('''CREATE TABLE IF NOT EXISTS files (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        file_id TEXT,
        file_name TEXT,
        file_type TEXT,
        category TEXT
    )''')
    conn.commit()
    cur.close()
    conn.close()
