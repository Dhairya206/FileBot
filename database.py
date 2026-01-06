import psycopg2
import os
from datetime import datetime, timedelta

DATABASE_URL = os.getenv('DATABASE_URL')

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # Users table
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        is_admin BOOLEAN DEFAULT FALSE,
        is_approved BOOLEAN DEFAULT FALSE,
        plan TEXT DEFAULT 'None',
        expiry_date TIMESTAMP,
        qr_link TEXT DEFAULT 'https://imgur.com/your_default_qr'
    )''')
    # Files table (Isolated storage)
    cur.execute('''CREATE TABLE IF NOT EXISTS files (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        file_id TEXT,
        file_name TEXT,
        file_type TEXT,
        encrypted BOOLEAN DEFAULT TRUE
    )''')
    conn.commit()
    cur.close()
    conn.close()

def is_admin(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT is_admin FROM users WHERE user_id = %s", (user_id,))
    res = cur.fetchone()
    return res[0] if res else False
