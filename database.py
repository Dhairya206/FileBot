import os
import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta
import logging
import uuid

logger = logging.getLogger(__name__)

def get_db_connection():
    """Create database connection"""
    DATABASE_URL = os.getenv('DATABASE_URL')
    
    # Fix for Railway
    if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Initialize all database tables"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                full_name TEXT,
                profile_link TEXT,
                approved BOOLEAN DEFAULT FALSE,
                admin_access BOOLEAN DEFAULT FALSE,
                admin_code_used TIMESTAMP,
                registration_date TIMESTAMP DEFAULT NOW(),
                last_active TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Subscriptions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                plan_type TEXT NOT NULL,
                price INTEGER NOT NULL,
                storage_limit BIGINT DEFAULT 5368709120, -- 5GB default
                expiry_date TIMESTAMP NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                purchase_date TIMESTAMP DEFAULT NOW(),
                payment_method TEXT,
                transaction_id TEXT
            )
        """)
        
        # Files table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size BIGINT NOT NULL,
                file_path TEXT,
                encrypted_data BYTEA,
                upload_date TIMESTAMP DEFAULT NOW(),
                last_accessed TIMESTAMP DEFAULT NOW(),
                access_count INTEGER DEFAULT 0,
                tags TEXT[]
            )
        """)
        
        # Categories table for file organization
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_categories (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                category_name TEXT NOT NULL,
                file_type TEXT, -- 'document', 'image', 'video', 'audio'
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, category_name)
            )
        """)
        
        # File-category mapping
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_category_map (
                file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
                category_id INTEGER REFERENCES file_categories(id) ON DELETE CASCADE,
                PRIMARY KEY (file_id, category_id)
            )
        """)
        
        # Tickets table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id SERIAL PRIMARY KEY,
                ticket_id TEXT UNIQUE NOT NULL,
                user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                ticket_type TEXT DEFAULT 'payment', -- 'payment', 'support', 'technical'
                status TEXT DEFAULT 'open', -- 'open', 'in_progress', 'closed', 'resolved'
                priority TEXT DEFAULT 'normal', -- 'low', 'normal', 'high', 'urgent'
                subject TEXT,
                description TEXT,
                assigned_to BIGINT, -- Admin telegram_id
                group_chat_id BIGINT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                closed_at TIMESTAMP,
                resolution TEXT
            )
        """)
        
        # Ticket messages
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ticket_messages (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                message_text TEXT,
                message_type TEXT DEFAULT 'text', -- 'text', 'photo', 'document', 'payment_proof'
                file_id TEXT,
                sent_at TIMESTAMP DEFAULT NOW(),
                is_read BOOLEAN DEFAULT FALSE
            )
        """)
        
        # Payments table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                amount INTEGER NOT NULL,
                plan_type TEXT NOT NULL,
                payment_method TEXT NOT NULL, -- 'upi', 'qr', 'cash', 'bank_transfer', 'redeem_code'
                transaction_id TEXT,
                status TEXT DEFAULT 'pending', -- 'pending', 'completed', 'failed', 'refunded'
                payment_date TIMESTAMP DEFAULT NOW(),
                verified_by BIGINT, -- Admin telegram_id
                verified_at TIMESTAMP,
                notes TEXT
            )
        """)
        
        # Redeem Codes table - NEW ADDITION
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS redeem_codes (
                id SERIAL PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                plan_type TEXT NOT NULL, -- 'monthly', 'quarterly', 'half_yearly', 'yearly'
                value INTEGER NOT NULL, -- Amount in rupees
                created_by BIGINT, -- Admin telegram_id
                created_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP,
                max_uses INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                used_by TEXT[], -- Array of user_ids who used this code
                notes TEXT
            )
        """)
        
        # Admin settings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_settings (
                id SERIAL PRIMARY KEY,
                setting_key TEXT UNIQUE NOT NULL,
                setting_value TEXT,
                setting_type TEXT DEFAULT 'text',
                updated_at TIMESTAMP DEFAULT NOW(),
                updated_by BIGINT
            )
        """)
        
        # QR Codes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS qr_codes (
                id SERIAL PRIMARY KEY,
                qr_type TEXT NOT NULL, -- 'upi', 'bank', 'payment'
                upi_id TEXT,
                bank_name TEXT,
                account_number TEXT,
                ifsc_code TEXT,
                qr_image_url TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # User activity logs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                activity_type TEXT NOT NULL, -- 'login', 'upload', 'download', 'view', 'delete'
                activity_details TEXT,
                ip_address TEXT,
                user_agent TEXT,
                activity_time TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Insert default admin settings
        cursor.execute("""
            INSERT INTO admin_settings (setting_key, setting_value, setting_type) VALUES
            ('admin_code', '2008', 'text'),
            ('default_storage_monthly', '5368709120', 'number'), -- 5GB
            ('default_storage_quarterly', '16106127360', 'number'), -- 15GB
            ('default_storage_half_yearly', '32212254720', 'number'), -- 30GB
            ('default_storage_yearly', '107374182400', 'number'), -- 100GB
            ('ticket_max_members', '5', 'number'),
            ('ticket_auto_close_hours', '48', 'number'),
            ('enable_youtube_download', 'true', 'boolean'),
            ('max_file_size_mb', '2048', 'number'), -- 2GB
            ('qr_upi_id', '7960003520@ybl', 'text'),
            ('redeem_code_expiry_days', '30', 'number'),
            ('redeem_code_prefix', 'RC', 'text')
            ON CONFLICT (setting_key) DO NOTHING
        """)
        
        # Insert default QR code
        cursor.execute("""
            INSERT INTO qr_codes (qr_type, upi_id, is_active) VALUES
            ('upi', '7960003520@ybl', true)
            ON CONFLICT DO NOTHING
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✅ Database initialized successfully")
        
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        raise

# ==================== USER FUNCTIONS ====================
def get_user(user_id):
    """Get user by telegram_id"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE telegram_id = %s",
            (user_id,)
        )
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        return user
    except Exception as e:
        logger.error(f"Get user error: {e}")
        return None

def create_user(telegram_id, username, full_name, profile_link):
    """Create new user"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (telegram_id, username, full_name, profile_link, registration_date)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (telegram_id) DO UPDATE SET
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            profile_link = EXCLUDED.profile_link,
            last_active = NOW()
            RETURNING id
            """,
            (telegram_id, username, full_name, profile_link)
        )
        user_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return user_id
    except Exception as e:
        logger.error(f"Create user error: {e}")
        return None

def approve_user(telegram_id):
    """Approve user registration"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET approved = TRUE, last_active = NOW() WHERE telegram_id = %s",
            (telegram_id,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Approve user error: {e}")
        return False

def set_admin(telegram_id, is_admin=True):
    """Set user as admin"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET admin_access = %s, admin_code_used = NOW() WHERE telegram_id = %s",
            (is_admin, telegram_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Set admin error: {e}")
        return False

# ==================== SUBSCRIPTION FUNCTIONS ====================
def add_subscription(user_id, plan_type, price, days, payment_method='redeem_code', transaction_id=None):
    """Add user subscription"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get storage limit based on plan
        cursor.execute(
            "SELECT setting_value FROM admin_settings WHERE setting_key = %s",
            (f'default_storage_{plan_type}',)
        )
        storage_limit = cursor.fetchone()
        storage_limit = int(storage_limit[0]) if storage_limit else 5368709120
        
        expiry_date = datetime.now().replace(microsecond=0) + timedelta(days=days)
        
        # Deactivate any existing subscription
        cursor.execute(
            "UPDATE subscriptions SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE",
            (user_id,)
        )
        
        # Add new subscription
        cursor.execute(
            """
            INSERT INTO subscriptions 
            (user_id, plan_type, price, storage_limit, expiry_date, is_active, purchase_date, payment_method, transaction_id)
            VALUES (%s, %s, %s, %s, %s, TRUE, NOW(), %s, %s)
            """,
            (user_id, plan_type, price, storage_limit, expiry_date, payment_method, transaction_id)
        )
        
        # Record payment
        cursor.execute(
            """
            INSERT INTO payments 
            (user_id, amount, plan_type, payment_method, transaction_id, status, payment_date, verified_by, verified_at)
            VALUES (%s, %s, %s, %s, %s, 'completed', NOW(), %s, NOW())
            """,
            (user_id, price, plan_type, payment_method, transaction_id, user_id)
        )
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Add subscription error: {e}")
        return False

def check_subscription(user_id):
    """Check if user has active subscription"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.*, u.approved 
            FROM subscriptions s
            JOIN users u ON s.user_id = u.telegram_id
            WHERE s.user_id = %s 
            AND s.is_active = TRUE 
            AND s.expiry_date > NOW()
            AND u.approved = TRUE
            """,
            (user_id,)
        )
        subscription = cursor.fetchone()
        cursor.close()
        conn.close()
        return subscription
    except Exception as e:
        logger.error(f"Check subscription error: {e}")
        return None

def get_user_subscription(user_id):
    """Get user's subscription details"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM subscriptions 
            WHERE user_id = %s 
            AND is_active = TRUE 
            ORDER BY purchase_date DESC 
            LIMIT 1
            """,
            (user_id,)
        )
        subscription = cursor.fetchone()
        cursor.close()
        conn.close()
        return subscription
    except Exception as e:
        logger.error(f"Get user subscription error: {e}")
        return None

# ==================== REDEEM CODE FUNCTIONS ====================
def create_redeem_code(plan_type, value, created_by, expires_days=30, max_uses=1, notes=""):
    """Create a new redeem code"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Generate unique code
        import random
        import string
        
        # Get prefix from settings
        cursor.execute(
            "SELECT setting_value FROM admin_settings WHERE setting_key = 'redeem_code_prefix'"
        )
        prefix_result = cursor.fetchone()
        prefix = prefix_result[0] if prefix_result else "RC"
        
        # Generate random part
        random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        code = f"{prefix}{random_part}"
        
        expires_at = datetime.now() + timedelta(days=expires_days)
        
        cursor.execute(
            """
            INSERT INTO redeem_codes 
            (code, plan_type, value, created_by, expires_at, max_uses, is_active, notes)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
            RETURNING code
            """,
            (code, plan_type, value, created_by, expires_at, max_uses, notes)
        )
        
        code = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        
        return code
    except Exception as e:
        logger.error(f"Create redeem code error: {e}")
        return None

def validate_redeem_code(code, user_id):
    """Validate and use a redeem code"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT * FROM redeem_codes 
            WHERE code = %s 
            AND is_active = TRUE 
            AND (expires_at IS NULL OR expires_at > NOW())
            AND (max_uses = 0 OR used_count < max_uses)
            """,
            (code,)
        )
        
        redeem_code = cursor.fetchone()
        
        if not redeem_code:
            cursor.close()
            conn.close()
            return None, "Invalid or expired code"
        
        # Check if user already used this code
        code_id = redeem_code[0]
        used_by = redeem_code[10] or []  # used_by array
        
        if str(user_id) in used_by:
            cursor.close()
            conn.close()
            return None, "You have already used this code"
        
        # Update code usage
        cursor.execute(
            """
            UPDATE redeem_codes 
            SET used_count = used_count + 1, 
                used_by = array_append(used_by, %s)
            WHERE id = %s 
            AND (max_uses = 0 OR used_count < max_uses)
            RETURNING plan_type, value
            """,
            (str(user_id), code_id)
        )
        
        updated = cursor.fetchone()
        
        if not updated:
            cursor.close()
            conn.close()
            return None, "Code usage limit reached"
        
        plan_type, value = updated
        
        # If all uses exhausted, deactivate code
        cursor.execute(
            """
            UPDATE redeem_codes 
            SET is_active = FALSE 
            WHERE id = %s 
            AND max_uses > 0 
            AND used_count >= max_uses
            """,
            (code_id,)
        )
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return {'plan_type': plan_type, 'value': value}, "Code validated successfully"
    except Exception as e:
        logger.error(f"Validate redeem code error: {e}")
        return None, f"Error: {str(e)}"

def get_redeem_codes(created_by=None, active_only=True):
    """Get all redeem codes"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if created_by:
            if active_only:
                cursor.execute(
                    """
                    SELECT * FROM redeem_codes 
                    WHERE created_by = %s 
                    AND is_active = TRUE
                    ORDER BY created_at DESC
                    """,
                    (created_by,)
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM redeem_codes 
                    WHERE created_by = %s
                    ORDER BY created_at DESC
                    """,
                    (created_by,)
                )
        else:
            if active_only:
                cursor.execute(
                    "SELECT * FROM redeem_codes WHERE is_active = TRUE ORDER BY created_at DESC"
                )
            else:
                cursor.execute(
                    "SELECT * FROM redeem_codes ORDER BY created_at DESC"
                )
        
        codes = cursor.fetchall()
        cursor.close()
        conn.close()
        return codes
    except Exception as e:
        logger.error(f"Get redeem codes error: {e}")
        return []

def deactivate_redeem_code(code):
    """Deactivate a redeem code"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE redeem_codes SET is_active = FALSE WHERE code = %s",
            (code,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Deactivate redeem code error: {e}")
        return False

# ==================== FILE FUNCTIONS ====================
def add_file(user_id, file_name, file_type, file_size, file_path=None, encrypted_data=None, tags=None):
    """Add file to database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO files 
            (user_id, file_name, file_type, file_size, file_path, encrypted_data, upload_date, tags)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
            RETURNING id
            """,
            (user_id, file_name, file_type, file_size, file_path, encrypted_data, tags or [])
        )
        file_id = cursor.fetchone()[0]
        
        conn.commit()
        cursor.close()
        conn.close()
        return file_id
    except Exception as e:
        logger.error(f"Add file error: {e}")
        return None

def get_user_files(user_id, file_type=None, limit=50, offset=0):
    """Get user's files with optional filtering"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if file_type:
            cursor.execute(
                """
                SELECT * FROM files 
                WHERE user_id = %s AND file_type = %s 
                ORDER BY upload_date DESC 
                LIMIT %s OFFSET %s
                """,
                (user_id, file_type, limit, offset)
            )
        else:
            cursor.execute(
                """
                SELECT * FROM files 
                WHERE user_id = %s 
                ORDER BY upload_date DESC 
                LIMIT %s OFFSET %s
                """,
                (user_id, limit, offset)
            )
        
        files = cursor.fetchall()
        cursor.close()
        conn.close()
        return files
    except Exception as e:
        logger.error(f"Get user files error: {e}")
        return []

def get_file_by_id(file_id):
    """Get file by ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM files WHERE id = %s",
            (file_id,)
        )
        file_data = cursor.fetchone()
        cursor.close()
        conn.close()
        return file_data
    except Exception as e:
        logger.error(f"Get file by ID error: {e}")
        return None

def delete_file(file_id):
    """Delete file from database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM files WHERE id = %s",
            (file_id,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Delete file error: {e}")
        return False

# ==================== TICKET FUNCTIONS ====================
def create_ticket(user_id, ticket_type='payment', subject='', description=''):
    """Create new ticket"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        import random
        import string
        ticket_id = f"TKT-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"
        
        cursor.execute(
            """
            INSERT INTO tickets 
            (ticket_id, user_id, ticket_type, subject, description, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 'open', NOW(), NOW())
            RETURNING id
            """,
            (ticket_id, user_id, ticket_type, subject, description)
        )
        
        ticket_db_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        
        return ticket_db_id, ticket_id
    except Exception as e:
        logger.error(f"Create ticket error: {e}")
        return None, None

def get_ticket(ticket_id):
    """Get ticket by ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM tickets WHERE ticket_id = %s",
            (ticket_id,)
        )
        ticket = cursor.fetchone()
        cursor.close()
        conn.close()
        return ticket
    except Exception as e:
        logger.error(f"Get ticket error: {e}")
        return None

def update_ticket_status(ticket_id, status, assigned_to=None, resolution=None):
    """Update ticket status"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if status == 'closed':
            cursor.execute(
                """
                UPDATE tickets 
                SET status = %s, assigned_to = %s, resolution = %s, closed_at = NOW(), updated_at = NOW()
                WHERE ticket_id = %s
                """,
                (status, assigned_to, resolution, ticket_id)
            )
        else:
            cursor.execute(
                """
                UPDATE tickets 
                SET status = %s, assigned_to = %s, resolution = %s, updated_at = NOW()
                WHERE ticket_id = %s
                """,
                (status, assigned_to, resolution, ticket_id)
            )
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Update ticket status error: {e}")
        return False

# ==================== PAYMENT FUNCTIONS ====================
def record_payment(user_id, amount, plan_type, payment_method, transaction_id, status='pending'):
    """Record a payment"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO payments 
            (user_id, amount, plan_type, payment_method, transaction_id, status, payment_date)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
            """,
            (user_id, amount, plan_type, payment_method, transaction_id, status)
        )
        
        payment_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        
        return payment_id
    except Exception as e:
        logger.error(f"Record payment error: {e}")
        return None

def verify_payment(payment_id, verified_by):
    """Verify a payment"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            UPDATE payments 
            SET status = 'completed', verified_by = %s, verified_at = NOW()
            WHERE id = %s
            RETURNING user_id, amount, plan_type
            """,
            (verified_by, payment_id)
        )
        
        payment_info = cursor.fetchone()
        
        if payment_info:
            user_id, amount, plan_type = payment_info
            
            # Add subscription
            days_map = {
                'monthly': 30,
                'quarterly': 90,
                'half_yearly': 180,
                'yearly': 365
            }
            
            days = days_map.get(plan_type, 30)
            add_subscription(user_id, plan_type, amount, days, 'manual', f"payment_{payment_id}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return True
    except Exception as e:
        logger.error(f"Verify payment error: {e}")
        return False

# ==================== ADMIN SETTINGS ====================
def get_admin_settings():
    """Get all admin settings"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admin_settings")
        settings = cursor.fetchall()
        cursor.close()
        conn.close()
        
        settings_dict = {}
        for setting in settings:
            settings_dict[setting[1]] = setting[2]  # key -> value
        return settings_dict
    except Exception as e:
        logger.error(f"Get admin settings error: {e}")
        return {}

def update_admin_setting(key, value, updated_by=None):
    """Update admin setting"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO admin_settings (setting_key, setting_value, updated_by, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (setting_key) 
            DO UPDATE SET 
            setting_value = EXCLUDED.setting_value,
            updated_by = EXCLUDED.updated_by,
            updated_at = EXCLUDED.updated_at
            """,
            (key, value, updated_by)
        )
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Update admin setting error: {e}")
        return False

# ==================== QR CODE FUNCTIONS ====================
def get_qr_code(qr_type='upi'):
    """Get active QR code"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM qr_codes WHERE qr_type = %s AND is_active = TRUE ORDER BY updated_at DESC LIMIT 1",
            (qr_type,)
        )
        qr_code = cursor.fetchone()
        cursor.close()
        conn.close()
        return qr_code
    except Exception as e:
        logger.error(f"Get QR code error: {e}")
        return None

def update_qr_code(qr_type, upi_id=None, bank_name=None, account_number=None, ifsc_code=None, qr_image_url=None):
    """Update QR code details"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Deactivate all existing QR codes of this type
        cursor.execute(
            "UPDATE qr_codes SET is_active = FALSE WHERE qr_type = %s",
            (qr_type,)
        )
        
        # Insert new active QR code
        cursor.execute(
            """
            INSERT INTO qr_codes 
            (qr_type, upi_id, bank_name, account_number, ifsc_code, qr_image_url, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
            """,
            (qr_type, upi_id, bank_name, account_number, ifsc_code, qr_image_url)
        )
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Update QR code error: {e}")
        return False

# ==================== ACTIVITY LOGGING ====================
def log_activity(user_id, activity_type, activity_details=None, ip_address=None, user_agent=None):
    """Log user activity"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO user_activity 
            (user_id, activity_type, activity_details, ip_address, user_agent, activity_time)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (user_id, activity_type, activity_details, ip_address, user_agent)
        )
        
        # Update user's last active time
        cursor.execute(
            "UPDATE users SET last_active = NOW() WHERE telegram_id = %s",
            (user_id,)
        )
        
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Log activity error: {e}")
        return False

# ==================== STATISTICS ====================
def get_user_stats(user_id):
    """Get user statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get total files count
        cursor.execute(
            "SELECT COUNT(*) FROM files WHERE user_id = %s",
            (user_id,)
        )
        total_files = cursor.fetchone()[0]
        
        # Get total storage used
        cursor.execute(
            "SELECT COALESCE(SUM(file_size), 0) FROM files WHERE user_id = %s",
            (user_id,)
        )
        storage_used = cursor.fetchone()[0]
        
        # Get file type distribution
        cursor.execute(
            """
            SELECT file_type, COUNT(*), COALESCE(SUM(file_size), 0)
            FROM files WHERE user_id = %s 
            GROUP BY file_type
            """,
            (user_id,)
        )
        file_types = cursor.fetchall()
        
        # Get subscription info
        cursor.execute(
            """
            SELECT plan_type, storage_limit, expiry_date 
            FROM subscriptions 
            WHERE user_id = %s AND is_active = TRUE AND expiry_date > NOW()
            """,
            (user_id,)
        )
        subscription = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        return {
            'total_files': total_files,
            'storage_used': storage_used,
            'file_types': file_types,
            'subscription': subscription
        }
    except Exception as e:
        logger.error(f"Get user stats error: {e}")
        return {'total_files': 0, 'storage_used': 0, 'file_types': [], 'subscription': None}

def get_all_users(approved_only=False):
    """Get all users"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if approved_only:
            cursor.execute(
                "SELECT * FROM users WHERE approved = TRUE ORDER BY registration_date DESC"
            )
        else:
            cursor.execute(
                "SELECT * FROM users ORDER BY registration_date DESC"
            )
        
        users = cursor.fetchall()
        cursor.close()
        conn.close()
        return users
    except Exception as e:
        logger.error(f"Get all users error: {e}")
        return []

def search_files(user_id, query):
    """Search files by name"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM files WHERE user_id = %s AND file_name ILIKE %s ORDER BY upload_date DESC",
            (user_id, f'%{query}%')
        )
        files = cursor.fetchall()
        cursor.close()
        conn.close()
        return files
    except Exception as e:
        logger.error(f"Search files error: {e}")
        return []