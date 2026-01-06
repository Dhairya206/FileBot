import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor, DictCursor
from dotenv import load_dotenv
import json
import hashlib

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.conn = None
        self.connect()
    
    def connect(self):
        """Establish database connection"""
        try:
            # Get database URL from environment (Railway/Koyeb provides this)
            database_url = os.getenv('DATABASE_URL')
            
            if not database_url:
                # Fallback to individual parameters
                self.conn = psycopg2.connect(
                    host=os.getenv('DB_HOST', 'localhost'),
                    database=os.getenv('DB_NAME', 'filex_bot'),
                    user=os.getenv('DB_USER', 'postgres'),
                    password=os.getenv('DB_PASSWORD', ''),
                    port=os.getenv('DB_PORT', '5432')
                )
            else:
                # Use connection string
                self.conn = psycopg2.connect(database_url, sslmode='require')
            
            # Create tables if they don't exist
            self.create_tables()
            logger.info("Database connection established successfully")
            
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise
    
    def create_tables(self):
        """Create all necessary tables"""
        commands = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(255),
                profile_link TEXT,
                secret_code_used BOOLEAN DEFAULT FALSE,
                secret_code_used_at TIMESTAMP,
                is_approved BOOLEAN DEFAULT FALSE,
                approved_at TIMESTAMP,
                approved_by INTEGER,
                subscription_plan VARCHAR(50),
                subscription_active BOOLEAN DEFAULT FALSE,
                subscription_expiry TIMESTAMP,
                storage_limit BIGINT DEFAULT 5368709120, -- 5GB in bytes
                storage_used BIGINT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS user_files (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                telegram_file_id TEXT NOT NULL,
                filename VARCHAR(500) NOT NULL,
                file_type VARCHAR(50), -- 'document', 'photo', 'video', 'audio'
                file_size BIGINT,
                mime_type VARCHAR(100),
                encryption_key TEXT, -- Encrypted key for E2EE
                is_encrypted BOOLEAN DEFAULT TRUE,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                tags TEXT[] DEFAULT '{}',
                metadata JSONB
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id VARCHAR(50) PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                ticket_type VARCHAR(50) NOT NULL, -- 'payment', 'support', 'issue'
                status VARCHAR(20) DEFAULT 'open', -- 'open', 'closed', 'resolved'
                plan_type VARCHAR(50),
                amount DECIMAL(10, 2),
                currency VARCHAR(10) DEFAULT 'INR',
                payment_method VARCHAR(50),
                payment_status VARCHAR(20) DEFAULT 'pending',
                telegram_group_id BIGINT,
                redeem_code VARCHAR(100),
                qr_code_data TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP,
                closed_by INTEGER
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                ticket_id VARCHAR(50) REFERENCES tickets(id),
                amount DECIMAL(10, 2) NOT NULL,
                currency VARCHAR(10) DEFAULT 'INR',
                payment_method VARCHAR(50),
                transaction_id VARCHAR(255),
                screenshot_url TEXT,
                status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'verified', 'rejected'
                verified_at TIMESTAMP,
                verified_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS youtube_downloads (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                video_url TEXT NOT NULL,
                video_id VARCHAR(100),
                title TEXT,
                quality VARCHAR(20),
                format_type VARCHAR(20), -- 'video', 'audio', 'slides'
                download_path TEXT,
                file_size BIGINT,
                duration INTEGER,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20) DEFAULT 'completed' -- 'pending', 'processing', 'completed', 'failed'
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS pdf_creations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                filename VARCHAR(500),
                page_size VARCHAR(20) DEFAULT 'A4',
                quality VARCHAR(20) DEFAULT 'medium',
                file_size BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                image_count INTEGER DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_logs (
                id SERIAL PRIMARY KEY,
                admin_id INTEGER,
                action VARCHAR(100) NOT NULL,
                target_user_id INTEGER,
                details JSONB,
                ip_address VARCHAR(45),
                user_agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS file_shares (
                id SERIAL PRIMARY KEY,
                file_id INTEGER REFERENCES user_files(id) ON DELETE CASCADE,
                sender_id INTEGER REFERENCES users(id),
                receiver_id INTEGER REFERENCES users(id),
                share_token VARCHAR(100) UNIQUE,
                expires_at TIMESTAMP,
                max_downloads INTEGER DEFAULT 1,
                download_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            # Create indexes for better performance
            """
            CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_active, subscription_expiry);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_user_files_user_id ON user_files(user_id);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_user_files_file_type ON user_files(file_type);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
            """
        ]
        
        with self.conn.cursor() as cursor:
            for command in commands:
                try:
                    cursor.execute(command)
                except Exception as e:
                    logger.error(f"Error creating table: {e}")
            self.conn.commit()
    
    # User Management Methods
    def add_user(self, telegram_id: int, username: str = None, profile_link: str = None) -> int:
        """Add new user to database"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO users (telegram_id, username, profile_link)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (telegram_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    profile_link = EXCLUDED.profile_link
                    RETURNING id
                """, (telegram_id, username, profile_link))
                
                result = cursor.fetchone()
                self.conn.commit()
                return result['id'] if result else None
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            self.conn.rollback()
            return None
    
    def get_user(self, telegram_id: int) -> Optional[Dict]:
        """Get user by Telegram ID"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM users WHERE telegram_id = %s
                """, (telegram_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Get user by database ID"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM users WHERE id = %s
                """, (user_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting user by ID: {e}")
            return None
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user by username"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM users WHERE username = %s
                """, (username,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting user by username: {e}")
            return None
    
    def approve_user(self, telegram_id: int, approved_by: int) -> bool:
        """Approve user access"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE users 
                    SET is_approved = TRUE, 
                        approved_at = CURRENT_TIMESTAMP,
                        approved_by = %s
                    WHERE telegram_id = %s
                """, (approved_by, telegram_id))
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error approving user: {e}")
            self.conn.rollback()
            return False
    
    def update_user_secret_code(self, telegram_id: int) -> bool:
        """Mark secret code as used"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE users 
                    SET secret_code_used = TRUE,
                        secret_code_used_at = CURRENT_TIMESTAMP
                    WHERE telegram_id = %s
                """, (telegram_id,))
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating secret code: {e}")
            self.conn.rollback()
            return False
    
    def update_user_subscription(self, user_id: int, plan_type: str, 
                                 expiry_date: datetime, is_active: bool = True) -> bool:
        """Update user subscription"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE users 
                    SET subscription_plan = %s,
                        subscription_active = %s,
                        subscription_expiry = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (plan_type, is_active, expiry_date, user_id))
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating subscription: {e}")
            self.conn.rollback()
            return False
    
    def update_user_storage_limit(self, user_id: int, storage_limit: int) -> bool:
        """Update user storage limit"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE users 
                    SET storage_limit = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (storage_limit, user_id))
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating storage limit: {e}")
            self.conn.rollback()
            return False
    
    def update_storage_used(self, user_id: int, file_size: int, operation: str = 'add') -> bool:
        """Update user's used storage (add or remove)"""
        try:
            with self.conn.cursor() as cursor:
                if operation == 'add':
                    cursor.execute("""
                        UPDATE users 
                        SET storage_used = storage_used + %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (file_size, user_id))
                else:  # remove
                    cursor.execute("""
                        UPDATE users 
                        SET storage_used = GREATEST(0, storage_used - %s),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (file_size, user_id))
                
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating storage used: {e}")
            self.conn.rollback()
            return False
    
    def get_all_users(self, only_active: bool = False) -> List[Dict]:
        """Get all users"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if only_active:
                    cursor.execute("""
                        SELECT * FROM users 
                        WHERE subscription_active = TRUE 
                        AND subscription_expiry > CURRENT_TIMESTAMP
                        ORDER BY created_at DESC
                    """)
                else:
                    cursor.execute("""
                        SELECT * FROM users ORDER BY created_at DESC
                    """)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    def get_expiring_subscriptions(self, days: int = 3) -> List[Dict]:
        """Get users with subscriptions expiring in X days"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM users 
                    WHERE subscription_active = TRUE 
                    AND subscription_expiry BETWEEN CURRENT_TIMESTAMP 
                    AND CURRENT_TIMESTAMP + INTERVAL '%s days'
                    ORDER BY subscription_expiry
                """, (days,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting expiring subscriptions: {e}")
            return []
    
    # File Management Methods
    def add_file(self, user_id: int, telegram_file_id: str, filename: str, 
                 file_type: str, file_size: int, mime_type: str = None, 
                 encryption_key: str = None) -> int:
        """Add file record to database"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO user_files 
                    (user_id, telegram_file_id, filename, file_type, file_size, 
                     mime_type, encryption_key, is_encrypted)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (user_id, telegram_file_id, filename, file_type, 
                      file_size, mime_type, encryption_key, encryption_key is not None))
                
                result = cursor.fetchone()
                self.conn.commit()
                
                # Update user's storage used
                if result:
                    self.update_storage_used(user_id, file_size, 'add')
                
                return result['id'] if result else None
        except Exception as e:
            logger.error(f"Error adding file: {e}")
            self.conn.rollback()
            return None
    
    def get_user_files(self, user_id: int, file_type: str = None, 
                       limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get user's files"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if file_type:
                    cursor.execute("""
                        SELECT * FROM user_files 
                        WHERE user_id = %s AND file_type = %s
                        ORDER BY uploaded_at DESC
                        LIMIT %s OFFSET %s
                    """, (user_id, file_type, limit, offset))
                else:
                    cursor.execute("""
                        SELECT * FROM user_files 
                        WHERE user_id = %s
                        ORDER BY uploaded_at DESC
                        LIMIT %s OFFSET %s
                    """, (user_id, limit, offset))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting user files: {e}")
            return []
    
    def get_user_file_by_name(self, user_id: int, filename: str) -> Optional[Dict]:
        """Get specific file by name"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM user_files 
                    WHERE user_id = %s AND filename = %s
                """, (user_id, filename))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting file by name: {e}")
            return None
    
    def get_user_files_info(self, user_id: int) -> Dict:
        """Get user's file statistics"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as file_count,
                        SUM(file_size) as total_size,
                        COUNT(DISTINCT file_type) as type_count
                    FROM user_files 
                    WHERE user_id = %s
                """, (user_id,))
                result = cursor.fetchone()
                
                # Get file type breakdown
                cursor.execute("""
                    SELECT 
                        file_type,
                        COUNT(*) as count,
                        SUM(file_size) as size
                    FROM user_files 
                    WHERE user_id = %s
                    GROUP BY file_type
                """, (user_id,))
                type_breakdown = cursor.fetchall()
                
                return {
                    'file_count': result['file_count'] or 0,
                    'total_size': result['total_size'] or 0,
                    'type_count': result['type_count'] or 0,
                    'type_breakdown': type_breakdown
                }
        except Exception as e:
            logger.error(f"Error getting files info: {e}")
            return {'file_count': 0, 'total_size': 0, 'type_count': 0, 'type_breakdown': []}
    
    def delete_file(self, file_id: int, user_id: int = None) -> bool:
        """Delete file from database"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # First get file size for storage update
                cursor.execute("""
                    SELECT file_size, user_id FROM user_files WHERE id = %s
                """, (file_id,))
                file_info = cursor.fetchone()
                
                if not file_info:
                    return False
                
                # Delete the file
                if user_id:
                    cursor.execute("""
                        DELETE FROM user_files WHERE id = %s AND user_id = %s
                    """, (file_id, user_id))
                else:
                    cursor.execute("""
                        DELETE FROM user_files WHERE id = %s
                    """, (file_id,))
                
                rows_deleted = cursor.rowcount
                
                if rows_deleted > 0:
                    # Update user's storage used
                    self.update_storage_used(file_info['user_id'], file_info['file_size'], 'remove')
                
                self.conn.commit()
                return rows_deleted > 0
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            self.conn.rollback()
            return False
    
    # Ticket Management Methods
    def create_ticket(self, user_id: int, ticket_type: str, plan_type: str = None, 
                      amount: float = None) -> str:
        """Create a new ticket"""
        try:
            ticket_id = hashlib.md5(f"{user_id}{datetime.now().timestamp()}".encode()).hexdigest()[:10]
            
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO tickets (id, user_id, ticket_type, plan_type, amount)
                    VALUES (%s, %s, %s, %s, %s)
                """, (ticket_id, user_id, ticket_type, plan_type, amount))
                
                self.conn.commit()
                return ticket_id
        except Exception as e:
            logger.error(f"Error creating ticket: {e}")
            self.conn.rollback()
            return None
    
    def get_ticket(self, ticket_id: str) -> Optional[Dict]:
        """Get ticket by ID"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM tickets WHERE id = %s
                """, (ticket_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting ticket: {e}")
            return None
    
    def get_user_tickets(self, user_id: int, status: str = None) -> List[Dict]:
        """Get user's tickets"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if status:
                    cursor.execute("""
                        SELECT * FROM tickets 
                        WHERE user_id = %s AND status = %s
                        ORDER BY created_at DESC
                    """, (user_id, status))
                else:
                    cursor.execute("""
                        SELECT * FROM tickets 
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                    """, (user_id,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting user tickets: {e}")
            return []
    
    def get_tickets_by_status(self, status: str = 'open') -> List[Dict]:
        """Get tickets by status"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM tickets 
                    WHERE status = %s
                    ORDER BY created_at DESC
                """, (status,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting tickets by status: {e}")
            return []
    
    def update_ticket_status(self, ticket_id: str, status: str, closed_by: int = None) -> bool:
        """Update ticket status"""
        try:
            with self.conn.cursor() as cursor:
                if status == 'closed' and closed_by:
                    cursor.execute("""
                        UPDATE tickets 
                        SET status = %s, closed_at = CURRENT_TIMESTAMP, closed_by = %s
                        WHERE id = %s
                    """, (status, closed_by, ticket_id))
                else:
                    cursor.execute("""
                        UPDATE tickets 
                        SET status = %s
                        WHERE id = %s
                    """, (status, ticket_id))
                
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating ticket status: {e}")
            self.conn.rollback()
            return False
    
    def update_ticket_group(self, ticket_id: str, group_id: int) -> bool:
        """Update ticket with Telegram group ID"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE tickets 
                    SET telegram_group_id = %s
                    WHERE id = %s
                """, (group_id, ticket_id))
                
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating ticket group: {e}")
            self.conn.rollback()
            return False
    
    def update_ticket_qr_code(self, ticket_id: str, qr_code_data: str) -> bool:
        """Update ticket with QR code data"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE tickets 
                    SET qr_code_data = %s
                    WHERE id = %s
                """, (qr_code_data, ticket_id))
                
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating ticket QR code: {e}")
            self.conn.rollback()
            return False
    
    def update_ticket_redeem_code(self, ticket_id: str, redeem_code: str) -> bool:
        """Update ticket with redeem code"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE tickets 
                    SET redeem_code = %s
                    WHERE id = %s
                """, (redeem_code, ticket_id))
                
                self.conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating ticket redeem code: {e}")
            self.conn.rollback()
            return False
    
    # YouTube Downloads Methods
    def add_youtube_download(self, user_id: int, video_url: str, video_id: str, 
                            title: str, quality: str, format_type: str) -> int:
        """Record YouTube download"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO youtube_downloads 
                    (user_id, video_url, video_id, title, quality, format_type)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (user_id, video_url, video_id, title, quality, format_type))
                
                result = cursor.fetchone()
                self.conn.commit()
                return result['id'] if result else None
        except Exception as e:
            logger.error(f"Error adding YouTube download: {e}")
            self.conn.rollback()
            return None
    
    def get_user_youtube_downloads(self, user_id: int, limit: int = 20) -> List[Dict]:
        """Get user's YouTube download history"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM youtube_downloads 
                    WHERE user_id = %s
                    ORDER BY downloaded_at DESC
                    LIMIT %s
                """, (user_id, limit))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting YouTube downloads: {e}")
            return []
    
    # PDF Creation Methods
    def add_pdf_creation(self, user_id: int, filename: str, page_size: str, 
                        quality: str, file_size: int, image_count: int) -> int:
        """Record PDF creation"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO pdf_creations 
                    (user_id, filename, page_size, quality, file_size, image_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (user_id, filename, page_size, quality, file_size, image_count))
                
                result = cursor.fetchone()
                self.conn.commit()
                return result['id'] if result else None
        except Exception as e:
            logger.error(f"Error adding PDF creation: {e}")
            self.conn.rollback()
            return None
    
    def get_user_pdf_creations(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Get user's PDF creation history"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM pdf_creations 
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (user_id, limit))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting PDF creations: {e}")
            return []
    
    # Admin Logging
    def log_admin_action(self, admin_id: int, action: str, 
                        target_user_id: int = None, details: Dict = None) -> bool:
        """Log admin actions"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO admin_logs (admin_id, action, target_user_id, details)
                    VALUES (%s, %s, %s, %s)
                """, (admin_id, action, target_user_id, json.dumps(details) if details else None))
                
                self.conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error logging admin action: {e}")
            self.conn.rollback()
            return False
    
    def get_admin_logs(self, admin_id: int = None, limit: int = 50) -> List[Dict]:
        """Get admin logs"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if admin_id:
                    cursor.execute("""
                        SELECT * FROM admin_logs 
                        WHERE admin_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (admin_id, limit))
                else:
                    cursor.execute("""
                        SELECT * FROM admin_logs 
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting admin logs: {e}")
            return []
    
    # Utility Methods
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
    
    def health_check(self) -> bool:
        """Check database connection health"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                return True
        except:
            return False
    
    def backup_database(self) -> str:
        """Create database backup (returns backup file path)"""
        # This is a simplified version
        # In production, you'd want to use pg_dump or similar
        backup_file = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        # Implement actual backup logic here
        return backup_file


def init_db():
    """Initialize database connection"""
    db = Database()
    return db