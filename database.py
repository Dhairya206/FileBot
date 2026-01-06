import asyncpg
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
import os
import json
from cryptography.fernet import Fernet
import hashlib
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.pool = None
        self.encryption_key = os.getenv('ENCRYPTION_KEY')
        if self.encryption_key:
            self.cipher = Fernet(self.encryption_key.encode())
        else:
            self.cipher = None
            logger.warning("ENCRYPTION_KEY not set, encryption disabled")
    
    async def create_pool(self):
        """Create database connection pool"""
        try:
            self.pool = await asyncpg.create_pool(
                host=os.getenv('DB_HOST', 'localhost'),
                port=int(os.getenv('DB_PORT', 5432)),
                user=os.getenv('DB_USER', 'postgres'),
                password=os.getenv('DB_PASSWORD', ''),
                database=os.getenv('DB_NAME', 'filex_bot'),
                min_size=5,
                max_size=20,
                command_timeout=60
            )
            await self.init_tables()
            logger.info("Database connection established")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise
    
    async def init_tables(self):
        """Initialize all required tables"""
        async with self.pool.acquire() as conn:
            # Users table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    profile_link TEXT,
                    secret_code VARCHAR(50),
                    is_approved BOOLEAN DEFAULT FALSE,
                    is_admin BOOLEAN DEFAULT FALSE,
                    is_banned BOOLEAN DEFAULT FALSE,
                    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    language_code VARCHAR(10) DEFAULT 'en',
                    settings JSONB DEFAULT '{}'::jsonb
                )
            ''')
            
            # Subscriptions table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS subscriptions (
                    sub_id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    plan_type VARCHAR(50),
                    storage_limit_gb INTEGER,
                    storage_used_gb FLOAT DEFAULT 0,
                    start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expiry_date TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    payment_method VARCHAR(100),
                    transaction_id VARCHAR(255),
                    auto_renew BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Files table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    file_id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    file_name VARCHAR(500),
                    file_type VARCHAR(50),
                    file_size BIGINT,
                    file_path TEXT,
                    telegram_file_id TEXT,
                    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_encrypted BOOLEAN DEFAULT TRUE,
                    encryption_key TEXT,
                    share_count INTEGER DEFAULT 0,
                    is_shared BOOLEAN DEFAULT FALSE,
                    shared_link VARCHAR(500),
                    description TEXT,
                    tags TEXT[] DEFAULT '{}',
                    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    access_count INTEGER DEFAULT 0
                )
            ''')
            
            # Payment tickets table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS payment_tickets (
                    ticket_id VARCHAR(50) PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    plan_type VARCHAR(50),
                    amount DECIMAL(10,2),
                    currency VARCHAR(10) DEFAULT 'INR',
                    status VARCHAR(20) DEFAULT 'pending',
                    payment_method VARCHAR(100),
                    qr_code_path TEXT,
                    upi_id VARCHAR(100),
                    bank_details JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP,
                    group_chat_id BIGINT,
                    admin_notes TEXT,
                    metadata JSONB DEFAULT '{}'::jsonb
                )
            ''')
            
            # Admin actions log
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS admin_logs (
                    log_id SERIAL PRIMARY KEY,
                    admin_id BIGINT,
                    action VARCHAR(100),
                    target_user_id BIGINT,
                    details TEXT,
                    ip_address VARCHAR(45),
                    user_agent TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # User sessions/logs
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_logs (
                    log_id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    action VARCHAR(100),
                    details TEXT,
                    ip_address VARCHAR(45),
                    user_agent TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # File access logs (for shared files)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS file_access_logs (
                    access_id SERIAL PRIMARY KEY,
                    file_id INTEGER REFERENCES files(file_id) ON DELETE CASCADE,
                    accessed_by BIGINT,
                    access_type VARCHAR(50),
                    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ip_address VARCHAR(45)
                )
            ''')
            
            # System settings
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS system_settings (
                    setting_id SERIAL PRIMARY KEY,
                    setting_key VARCHAR(100) UNIQUE,
                    setting_value TEXT,
                    setting_type VARCHAR(50),
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by BIGINT
                )
            ''')
            
            # Create indexes for performance
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_users_approved 
                ON users(is_approved) WHERE is_approved = TRUE
            ''')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_users_banned 
                ON users(is_banned) WHERE is_banned = TRUE
            ''')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_subscriptions_active 
                ON subscriptions(is_active) WHERE is_active = TRUE
            ''')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_subscriptions_expiry 
                ON subscriptions(expiry_date) WHERE is_active = TRUE
            ''')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_files_user 
                ON files(user_id)
            ''')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_files_upload_date 
                ON files(upload_date DESC)
            ''')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_tickets_status 
                ON payment_tickets(status)
            ''')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_tickets_created 
                ON payment_tickets(created_at DESC)
            ''')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_admin_logs_admin 
                ON admin_logs(admin_id)
            ''')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_logs_user 
                ON user_logs(user_id)
            ''')
            
            # Insert default admin if specified in environment
            admin_id = os.getenv('ADMIN_USER_ID')
            if admin_id:
                await conn.execute('''
                    INSERT INTO users (user_id, username, first_name, is_admin, is_approved)
                    VALUES ($1, $2, $3, TRUE, TRUE)
                    ON CONFLICT (user_id) DO UPDATE 
                    SET is_admin = TRUE, is_approved = TRUE
                ''', int(admin_id), 'admin', 'Admin')
            
            # Insert default system settings
            default_settings = [
                ('bot_name', 'TheFilex Bot', 'string', 'Bot display name'),
                ('maintenance_mode', 'false', 'boolean', 'Maintenance mode status'),
                ('max_file_size', '524288000', 'integer', 'Maximum file size in bytes (500MB)'),
                ('allowed_file_types', 'pdf,doc,docx,txt,jpg,jpeg,png,gif,mp4,mp3,avi,mkv,zip,rar', 'string', 'Allowed file extensions'),
                ('storage_warning_threshold', '90', 'integer', 'Storage warning percentage'),
                ('auto_delete_expired', 'true', 'boolean', 'Auto delete expired subscriptions'),
                ('backup_interval', '24', 'integer', 'Backup interval in hours'),
                ('support_contact', '@support', 'string', 'Support contact username'),
                ('payment_expiry_hours', '24', 'integer', 'Payment ticket expiry in hours'),
                ('default_language', 'en', 'string', 'Default bot language')
            ]
            
            for key, value, value_type, description in default_settings:
                await conn.execute('''
                    INSERT INTO system_settings (setting_key, setting_value, setting_type, description)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (setting_key) DO NOTHING
                ''', key, value, value_type, description)
            
            logger.info("Database tables initialized successfully")
    
    # ==================== USER MANAGEMENT ====================
    
    async def create_user(self, user_id: int, username: str, first_name: str, 
                         last_name: str = None, profile_link: str = None) -> bool:
        """Create a new user"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO users (user_id, username, first_name, last_name, profile_link)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (user_id) DO UPDATE 
                    SET username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        profile_link = EXCLUDED.profile_link,
                        last_active = CURRENT_TIMESTAMP
                ''', user_id, username, first_name, last_name, profile_link)
                return True
        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
            return False
    
    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        try:
            async with self.pool.acquire() as conn:
                user = await conn.fetchrow('''
                    SELECT * FROM users WHERE user_id = $1
                ''', user_id)
                return dict(user) if user else None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    async def update_user(self, user_id: int, **kwargs) -> bool:
        """Update user information"""
        if not kwargs:
            return False
        
        try:
            async with self.pool.acquire() as conn:
                set_clause = ', '.join([f"{k} = ${i+2}" for i, k in enumerate(kwargs.keys())])
                values = [user_id] + list(kwargs.values())
                
                await conn.execute(f'''
                    UPDATE users 
                    SET {set_clause}, last_active = CURRENT_TIMESTAMP
                    WHERE user_id = $1
                ''', *values)
                return True
        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            return False
    
    async def approve_user(self, user_id: int) -> bool:
        """Approve a user"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE users 
                    SET is_approved = TRUE, secret_code = NULL
                    WHERE user_id = $1
                ''', user_id)
                return True
        except Exception as e:
            logger.error(f"Error approving user {user_id}: {e}")
            return False
    
    async def ban_user(self, user_id: int) -> bool:
        """Ban a user"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE users 
                    SET is_banned = TRUE, is_approved = FALSE
                    WHERE user_id = $1
                ''', user_id)
                return True
        except Exception as e:
            logger.error(f"Error banning user {user_id}: {e}")
            return False
    
    async def unban_user(self, user_id: int) -> bool:
        """Unban a user"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE users 
                    SET is_banned = FALSE, is_approved = TRUE
                    WHERE user_id = $1
                ''', user_id)
                return True
        except Exception as e:
            logger.error(f"Error unbanning user {user_id}: {e}")
            return False
    
    async def get_all_users(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get all users with pagination"""
        try:
            async with self.pool.acquire() as conn:
                users = await conn.fetch('''
                    SELECT * FROM users 
                    ORDER BY join_date DESC 
                    LIMIT $1 OFFSET $2
                ''', limit, offset)
                return [dict(user) for user in users]
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return []
    
    async def get_pending_users(self) -> List[Dict]:
        """Get users pending approval"""
        try:
            async with self.pool.acquire() as conn:
                users = await conn.fetch('''
                    SELECT * FROM users 
                    WHERE is_approved = FALSE AND is_banned = FALSE
                    ORDER BY join_date DESC
                ''')
                return [dict(user) for user in users]
        except Exception as e:
            logger.error(f"Error getting pending users: {e}")
            return []
    
    async def get_active_users_count(self, days: int = 7) -> int:
        """Count active users in last N days"""
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval('''
                    SELECT COUNT(*) FROM users 
                    WHERE last_active > CURRENT_TIMESTAMP - INTERVAL '$1 days'
                    AND is_approved = TRUE AND is_banned = FALSE
                ''', days)
                return count
        except Exception as e:
            logger.error(f"Error counting active users: {e}")
            return 0
    
    # ==================== SUBSCRIPTION MANAGEMENT ====================
    
    async def create_subscription(self, user_id: int, plan_type: str, 
                                 storage_limit_gb: int, duration_days: int,
                                 payment_method: str = None, transaction_id: str = None) -> bool:
        """Create a new subscription"""
        try:
            async with self.pool.acquire() as conn:
                start_date = datetime.now()
                expiry_date = start_date + timedelta(days=duration_days)
                
                # Deactivate any existing subscription
                await conn.execute('''
                    UPDATE subscriptions 
                    SET is_active = FALSE 
                    WHERE user_id = $1 AND is_active = TRUE
                ''', user_id)
                
                # Create new subscription
                await conn.execute('''
                    INSERT INTO subscriptions 
                    (user_id, plan_type, storage_limit_gb, start_date, expiry_date, 
                     payment_method, transaction_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                ''', user_id, plan_type, storage_limit_gb, start_date, 
                   expiry_date, payment_method, transaction_id)
                
                return True
        except Exception as e:
            logger.error(f"Error creating subscription for user {user_id}: {e}")
            return False
    
    async def get_user_subscription(self, user_id: int) -> Optional[Dict]:
        """Get active subscription for user"""
        try:
            async with self.pool.acquire() as conn:
                sub = await conn.fetchrow('''
                    SELECT * FROM subscriptions 
                    WHERE user_id = $1 AND is_active = TRUE
                    ORDER BY expiry_date DESC 
                    LIMIT 1
                ''', user_id)
                return dict(sub) if sub else None
        except Exception as e:
            logger.error(f"Error getting subscription for user {user_id}: {e}")
            return None
    
    async def update_storage_usage(self, user_id: int, file_size_gb: float, 
                                  operation: str = 'add') -> bool:
        """Update user's storage usage"""
        try:
            async with self.pool.acquire() as conn:
                if operation == 'add':
                    await conn.execute('''
                        UPDATE subscriptions 
                        SET storage_used_gb = storage_used_gb + $1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = $2 AND is_active = TRUE
                    ''', file_size_gb, user_id)
                elif operation == 'remove':
                    await conn.execute('''
                        UPDATE subscriptions 
                        SET storage_used_gb = GREATEST(storage_used_gb - $1, 0),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE user_id = $2 AND is_active = TRUE
                    ''', file_size_gb, user_id)
                return True
        except Exception as e:
            logger.error(f"Error updating storage for user {user_id}: {e}")
            return False
    
    async def check_storage_available(self, user_id: int, file_size_gb: float) -> bool:
        """Check if user has enough storage"""
        try:
            async with self.pool.acquire() as conn:
                sub = await conn.fetchrow('''
                    SELECT storage_limit_gb, storage_used_gb 
                    FROM subscriptions 
                    WHERE user_id = $1 AND is_active = TRUE
                ''', user_id)
                
                if not sub:
                    return False
                
                available = sub['storage_limit_gb'] - sub['storage_used_gb']
                return available >= file_size_gb
        except Exception as e:
            logger.error(f"Error checking storage for user {user_id}: {e}")
            return False
    
    async def get_expiring_subscriptions(self, days: int = 3) -> List[Dict]:
        """Get subscriptions expiring in next N days"""
        try:
            async with self.pool.acquire() as conn:
                subs = await conn.fetch('''
                    SELECT s.*, u.username, u.user_id
                    FROM subscriptions s
                    JOIN users u ON s.user_id = u.user_id
                    WHERE s.is_active = TRUE 
                    AND s.expiry_date BETWEEN CURRENT_TIMESTAMP 
                    AND CURRENT_TIMESTAMP + INTERVAL '$1 days'
                    ORDER BY s.expiry_date
                ''', days)
                return [dict(sub) for sub in subs]
        except Exception as e:
            logger.error(f"Error getting expiring subscriptions: {e}")
            return []
    
    async def renew_subscription(self, user_id: int, plan_type: str, 
                                duration_days: int) -> bool:
        """Renew user subscription"""
        try:
            async with self.pool.acquire() as conn:
                # Get current subscription
                current = await conn.fetchrow('''
                    SELECT * FROM subscriptions 
                    WHERE user_id = $1 AND is_active = TRUE
                ''', user_id)
                
                if not current:
                    return False
                
                # Calculate new expiry date
                if current['expiry_date'] > datetime.now():
                    # Extend from current expiry
                    new_expiry = current['expiry_date'] + timedelta(days=duration_days)
                else:
                    # Start from now
                    new_expiry = datetime.now() + timedelta(days=duration_days)
                
                await conn.execute('''
                    UPDATE subscriptions 
                    SET plan_type = $1, expiry_date = $2, 
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = $3 AND is_active = TRUE
                ''', plan_type, new_expiry, user_id)
                
                return True
        except Exception as e:
            logger.error(f"Error renewing subscription for user {user_id}: {e}")
            return False
    
    async def get_all_active_subscriptions(self) -> List[Dict]:
        """Get all active subscriptions"""
        try:
            async with self.pool.acquire() as conn:
                subs = await conn.fetch('''
                    SELECT s.*, u.username 
                    FROM subscriptions s
                    JOIN users u ON s.user_id = u.user_id
                    WHERE s.is_active = TRUE
                    ORDER BY s.expiry_date
                ''')
                return [dict(sub) for sub in subs]
        except Exception as e:
            logger.error(f"Error getting active subscriptions: {e}")
            return []
    
    # ==================== FILE MANAGEMENT ====================
    
    async def add_file(self, user_id: int, file_name: str, file_type: str, 
                      file_size: int, file_path: str, telegram_file_id: str,
                      description: str = None, tags: List[str] = None) -> Optional[int]:
        """Add a new file record"""
        try:
            async with self.pool.acquire() as conn:
                # Encrypt file path if encryption is enabled
                if self.cipher:
                    encrypted_path = self.cipher.encrypt(file_path.encode()).decode()
                else:
                    encrypted_path = file_path
                
                # Generate encryption key for file
                encryption_key = Fernet.generate_key().decode() if self.cipher else None
                
                file_id = await conn.fetchval('''
                    INSERT INTO files 
                    (user_id, file_name, file_type, file_size, file_path, 
                     telegram_file_id, encryption_key, description, tags)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING file_id
                ''', user_id, file_name, file_type, file_size, encrypted_path, 
                   telegram_file_id, encryption_key, description, tags or [])
                
                # Update storage usage
                file_size_gb = file_size / (1024 ** 3)  # Convert bytes to GB
                await self.update_storage_usage(user_id, file_size_gb, 'add')
                
                return file_id
        except Exception as e:
            logger.error(f"Error adding file for user {user_id}: {e}")
            return None
    
    async def get_file(self, file_id: int) -> Optional[Dict]:
        """Get file by ID"""
        try:
            async with self.pool.acquire() as conn:
                file = await conn.fetchrow('''
                    SELECT * FROM files WHERE file_id = $1
                ''', file_id)
                
                if not file:
                    return None
                
                file_dict = dict(file)
                
                # Decrypt file path if encrypted
                if file_dict['is_encrypted'] and self.cipher and file_dict['file_path']:
                    file_dict['file_path'] = self.cipher.decrypt(
                        file_dict['file_path'].encode()
                    ).decode()
                
                return file_dict
        except Exception as e:
            logger.error(f"Error getting file {file_id}: {e}")
            return None
    
    async def get_user_files(self, user_id: int, limit: int = 50, 
                            offset: int = 0) -> List[Dict]:
        """Get files for a specific user"""
        try:
            async with self.pool.acquire() as conn:
                files = await conn.fetch('''
                    SELECT * FROM files 
                    WHERE user_id = $1 
                    ORDER BY upload_date DESC 
                    LIMIT $2 OFFSET $3
                ''', user_id, limit, offset)
                
                result = []
                for file in files:
                    file_dict = dict(file)
                    
                    # Decrypt file path
                    if file_dict['is_encrypted'] and self.cipher and file_dict['file_path']:
                        file_dict['file_path'] = self.cipher.decrypt(
                            file_dict['file_path'].encode()
                        ).decode()
                    
                    result.append(file_dict)
                
                return result
        except Exception as e:
            logger.error(f"Error getting files for user {user_id}: {e}")
            return []
    
    async def delete_file(self, file_id: int, user_id: int = None) -> bool:
        """Delete a file"""
        try:
            async with self.pool.acquire() as conn:
                # Get file size for storage update
                file = await conn.fetchrow('''
                    SELECT file_size, user_id FROM files WHERE file_id = $1
                ''', file_id)
                
                if not file:
                    return False
                
                # Check permission if user_id provided
                if user_id and file['user_id'] != user_id:
                    return False
                
                # Delete file record
                await conn.execute('DELETE FROM files WHERE file_id = $1', file_id)
                
                # Update storage usage
                file_size_gb = file['file_size'] / (1024 ** 3)
                await self.update_storage_usage(file['user_id'], file_size_gb, 'remove')
                
                # Also delete from file access logs
                await conn.execute('DELETE FROM file_access_logs WHERE file_id = $1', file_id)
                
                return True
        except Exception as e:
            logger.error(f"Error deleting file {file_id}: {e}")
            return False
    
    async def share_file(self, file_id: int, shared_link: str = None) -> bool:
        """Share a file (make it publicly accessible)"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE files 
                    SET is_shared = TRUE, shared_link = $1,
                        last_accessed = CURRENT_TIMESTAMP
                    WHERE file_id = $2
                ''', shared_link, file_id)
                return True
        except Exception as e:
            logger.error(f"Error sharing file {file_id}: {e}")
            return False
    
    async def unshare_file(self, file_id: int) -> bool:
        """Unshare a file"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE files 
                    SET is_shared = FALSE, shared_link = NULL
                    WHERE file_id = $1
                ''', file_id)
                return True
        except Exception as e:
            logger.error(f"Error unsharing file {file_id}: {e}")
            return False
    
    async def get_shared_files(self) -> List[Dict]:
        """Get all shared files"""
        try:
            async with self.pool.acquire() as conn:
                files = await conn.fetch('''
                    SELECT * FROM files 
                    WHERE is_shared = TRUE 
                    ORDER BY upload_date DESC
                ''')
                return [dict(file) for file in files]
        except Exception as e:
            logger.error(f"Error getting shared files: {e}")
            return []
    
    async def increment_file_access(self, file_id: int, accessed_by: int = None) -> bool:
        """Increment file access count"""
        try:
            async with self.pool.acquire() as conn:
                # Update file access count
                await conn.execute('''
                    UPDATE files 
                    SET access_count = access_count + 1,
                        last_accessed = CURRENT_TIMESTAMP
                    WHERE file_id = $1
                ''', file_id)
                
                # Log access if accessed_by provided
                if accessed_by:
                    await conn.execute('''
                        INSERT INTO file_access_logs (file_id, accessed_by, access_type)
                        VALUES ($1, $2, 'view')
                    ''', file_id, accessed_by)
                
                return True
        except Exception as e:
            logger.error(f"Error incrementing file access {file_id}: {e}")
            return False
    
    async def search_files(self, user_id: int, query: str, 
                          file_type: str = None) -> List[Dict]:
        """Search files by name or description"""
        try:
            async with self.pool.acquire() as conn:
                if file_type:
                    files = await conn.fetch('''
                        SELECT * FROM files 
                        WHERE user_id = $1 
                        AND (file_name ILIKE $2 OR description ILIKE $2)
                        AND file_type = $3
                        ORDER BY upload_date DESC
                    ''', user_id, f"%{query}%", file_type)
                else:
                    files = await conn.fetch('''
                        SELECT * FROM files 
                        WHERE user_id = $1 
                        AND (file_name ILIKE $2 OR description ILIKE $2)
                        ORDER BY upload_date DESC
                    ''', user_id, f"%{query}%")
                
                result = []
                for file in files:
                    file_dict = dict(file)
                    
                    # Decrypt file path
                    if file_dict['is_encrypted'] and self.cipher and file_dict['file_path']:
                        file_dict['file_path'] = self.cipher.decrypt(
                            file_dict['file_path'].encode()
                        ).decode()
                    
                    result.append(file_dict)
                
                return result
        except Exception as e:
            logger.error(f"Error searching files for user {user_id}: {e}")
            return []
    
    # ==================== PAYMENT TICKET MANAGEMENT ====================
    
    async def create_payment_ticket(self, ticket_id: str, user_id: int, 
                                   plan_type: str, amount: float,
                                   payment_method: str = None, 
                                   qr_code_path: str = None,
                                   upi_id: str = None,
                                   bank_details: Dict = None) -> bool:
        """Create a new payment ticket"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO payment_tickets 
                    (ticket_id, user_id, plan_type, amount, payment_method,
                     qr_code_path, upi_id, bank_details)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ''', ticket_id, user_id, plan_type, amount, payment_method,
                   qr_code_path, upi_id, json.dumps(bank_details) if bank_details else None)
                return True
        except Exception as e:
            logger.error(f"Error creating payment ticket {ticket_id}: {e}")
            return False
    
    async def get_payment_ticket(self, ticket_id: str) -> Optional[Dict]:
        """Get payment ticket by ID"""
        try:
            async with self.pool.acquire() as conn:
                ticket = await conn.fetchrow('''
                    SELECT * FROM payment_tickets WHERE ticket_id = $1
                ''', ticket_id)
                
                if not ticket:
                    return None
                
                ticket_dict = dict(ticket)
                
                # Parse JSON fields
                if ticket_dict.get('bank_details'):
                    ticket_dict['bank_details'] = json.loads(ticket_dict['bank_details'])
                if ticket_dict.get('metadata'):
                    ticket_dict['metadata'] = json.loads(ticket_dict['metadata'])
                
                return ticket_dict
        except Exception as e:
            logger.error(f"Error getting payment ticket {ticket_id}: {e}")
            return None
    
    async def update_payment_ticket(self, ticket_id: str, **kwargs) -> bool:
        """Update payment ticket"""
        if not kwargs:
            return False
        
        try:
            async with self.pool.acquire() as conn:
                set_clause = ', '.join([f"{k} = ${i+2}" for i, k in enumerate(kwargs.keys())])
                values = [ticket_id] + list(kwargs.values())
                
                await conn.execute(f'''
                    UPDATE payment_tickets 
                    SET {set_clause}
                    WHERE ticket_id = $1
                ''', *values)
                return True
        except Exception as e:
            logger.error(f"Error updating payment ticket {ticket_id}: {e}")
            return False
    
    async def get_pending_tickets(self, limit: int = 100) -> List[Dict]:
        """Get pending payment tickets"""
        try:
            async with self.pool.acquire() as conn:
                tickets = await conn.fetch('''
                    SELECT t.*, u.username, u.first_name 
                    FROM payment_tickets t
                    JOIN users u ON t.user_id = u.user_id
                    WHERE t.status = 'pending'
                    ORDER BY t.created_at DESC 
                    LIMIT $1
                ''', limit)
                
                result = []
                for ticket in tickets:
                    ticket_dict = dict(ticket)
                    
                    # Parse JSON fields
                    if ticket_dict.get('bank_details'):
                        ticket_dict['bank_details'] = json.loads(ticket_dict['bank_details'])
                    if ticket_dict.get('metadata'):
                        ticket_dict['metadata'] = json.loads(ticket_dict['metadata'])
                    
                    result.append(ticket_dict)
                
                return result
        except Exception as e:
            logger.error(f"Error getting pending tickets: {e}")
            return []
    
    async def get_tickets_by_status(self, status: str, limit: int = 100) -> List[Dict]:
        """Get tickets by status"""
        try:
            async with self.pool.acquire() as conn:
                tickets = await conn.fetch('''
                    SELECT t.*, u.username, u.first_name 
                    FROM payment_tickets t
                    JOIN users u ON t.user_id = u.user_id
                    WHERE t.status = $1
                    ORDER BY t.created_at DESC 
                    LIMIT $2
                ''', status, limit)
                
                result = []
                for ticket in tickets:
                    ticket_dict = dict(ticket)
                    
                    # Parse JSON fields
                    if ticket_dict.get('bank_details'):
                        ticket_dict['bank_details'] = json.loads(ticket_dict['bank_details'])
                    if ticket_dict.get('metadata'):
                        ticket_dict['metadata'] = json.loads(ticket_dict['metadata'])
                    
                    result.append(ticket_dict)
                
                return result
        except Exception as e:
            logger.error(f"Error getting tickets by status {status}: {e}")
            return []
    
    async def mark_ticket_completed(self, ticket_id: str, admin_notes: str = None) -> bool:
        """Mark payment ticket as completed"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE payment_tickets 
                    SET status = 'completed', 
                        processed_at = CURRENT_TIMESTAMP,
                        admin_notes = $1
                    WHERE ticket_id = $2
                ''', admin_notes, ticket_id)
                return True
        except Exception as e:
            logger.error(f"Error marking ticket {ticket_id} as completed: {e}")
            return False
    
    async def mark_ticket_failed(self, ticket_id: str, admin_notes: str = None) -> bool:
        """Mark payment ticket as failed"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE payment_tickets 
                    SET status = 'failed', 
                        processed_at = CURRENT_TIMESTAMP,
                        admin_notes = $1
                    WHERE ticket_id = $2
                ''', admin_notes, ticket_id)
                return True
        except Exception as e:
            logger.error(f"Error marking ticket {ticket_id} as failed: {e}")
            return False
    
    async def get_user_tickets(self, user_id: int, limit: int = 50) -> List[Dict]:
        """Get payment tickets for a specific user"""
        try:
            async with self.pool.acquire() as conn:
                tickets = await conn.fetch('''
                    SELECT * FROM payment_tickets 
                    WHERE user_id = $1 
                    ORDER BY created_at DESC 
                    LIMIT $2
                ''', user_id, limit)
                
                result = []
                for ticket in tickets:
                    ticket_dict = dict(ticket)
                    
                    # Parse JSON fields
                    if ticket_dict.get('bank_details'):
                        ticket_dict['bank_details'] = json.loads(ticket_dict['bank_details'])
                    if ticket_dict.get('metadata'):
                        ticket_dict['metadata'] = json.loads(ticket_dict['metadata'])
                    
                    result.append(ticket_dict)
                
                return result
        except Exception as e:
            logger.error(f"Error getting tickets for user {user_id}: {e}")
            return []
    
    # ==================== STATISTICS & ANALYTICS ====================
    
    async def get_system_stats(self) -> Dict:
        """Get comprehensive system statistics"""
        try:
            async with self.pool.acquire() as conn:
                stats = {}
                
                # User statistics
                stats['total_users'] = await conn.fetchval("SELECT COUNT(*) FROM users")
                stats['approved_users'] = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE is_approved = TRUE"
                )
                stats['pending_users'] = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE is_approved = FALSE AND is_banned = FALSE"
                )
                stats['banned_users'] = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE is_banned = TRUE"
                )
                stats['admin_users'] = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE is_admin = TRUE"
                )
                
                # Subscription statistics
                stats['active_subscriptions'] = await conn.fetchval(
                    "SELECT COUNT(*) FROM subscriptions WHERE is_active = TRUE"
                )
                stats['total_storage_limit'] = await conn.fetchval(
                    "SELECT COALESCE(SUM(storage_limit_gb), 0) FROM subscriptions WHERE is_active = TRUE"
                )
                stats['total_storage_used'] = await conn.fetchval(
                    "SELECT COALESCE(SUM(storage_used_gb), 0) FROM subscriptions WHERE is_active = TRUE"
                )
                
                # File statistics
                stats['total_files'] = await conn.fetchval("SELECT COUNT(*) FROM files")
                stats['shared_files'] = await conn.fetchval(
                    "SELECT COUNT(*) FROM files WHERE is_shared = TRUE"
                )
                stats['total_file_size'] = await conn.fetchval(
                    "SELECT COALESCE(SUM(file_size), 0) FROM files"
                )
                
                # Payment statistics
                stats['total_revenue'] = await conn.fetchval(
                    "SELECT COALESCE(SUM(amount), 0) FROM payment_tickets WHERE status = 'completed'"
                )
                stats['pending_payments'] = await conn.fetchval(
                    "SELECT COUNT(*) FROM payment_tickets WHERE status = 'pending'"
                )
                stats['completed_payments'] = await conn.fetchval(
                    "SELECT COUNT(*) FROM payment_tickets WHERE status = 'completed'"
                )
                
                # Recent growth (last 7 days)
                stats['new_users_7d'] = await conn.fetchval('''
                    SELECT COUNT(*) FROM users 
                    WHERE join_date > CURRENT_TIMESTAMP - INTERVAL '7 days'
                ''')
                stats['new_files_7d'] = await conn.fetchval('''
                    SELECT COUNT(*) FROM files 
                    WHERE upload_date > CURRENT_TIMESTAMP - INTERVAL '7 days'
                ''')
                
               return stats
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
            return {}
    
    async def get_daily_stats(self, days: int = 30) -> List[Dict]:
        """Get daily statistics for the last N days"""
        try:
            async with self.pool.acquire() as conn:
                stats = await conn.fetch('''
                    SELECT 
                        DATE(join_date) as date,
                        COUNT(*) as new_users,
                        (SELECT COUNT(*) FROM files WHERE DATE(upload_date) = DATE(u.join_date)) as new_files,
                        (SELECT COALESCE(SUM(amount), 0) FROM payment_tickets 
                         WHERE status = 'completed' AND DATE(created_at) = DATE(u.join_date)) as revenue
                    FROM users u
                    WHERE join_date > CURRENT_TIMESTAMP - INTERVAL '$1 days'
                    GROUP BY DATE(join_date)
                    ORDER BY date DESC
                ''', days)
                return [dict(stat) for stat in stats]
        except Exception as e:
            logger.error(f"Error getting daily stats: {e}")
            return []
    
    # ==================== ADMIN LOGGING ====================
    
    async def log_admin_action(self, admin_id: int, action: str, 
                              target_user_id: int = None, details: str = "",
                              ip_address: str = None, user_agent: str = None) -> bool:
        """Log an admin action"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO admin_logs 
                    (admin_id, action, target_user_id, details, ip_address, user_agent)
                    VALUES ($1, $2, $3, $4, $5, $6)
                ''', admin_id, action, target_user_id, details, ip_address, user_agent)
                return True
        except Exception as e:
            logger.error(f"Error logging admin action: {e}")
            return False
    
    async def get_admin_logs(self, admin_id: int = None, limit: int = 100) -> List[Dict]:
        """Get admin logs"""
        try:
            async with self.pool.acquire() as conn:
                if admin_id:
                    logs = await conn.fetch('''
                        SELECT * FROM admin_logs 
                        WHERE admin_id = $1 
                        ORDER BY timestamp DESC 
                        LIMIT $2
                    ''', admin_id, limit)
                else:
                    logs = await conn.fetch('''
                        SELECT * FROM admin_logs 
                        ORDER BY timestamp DESC 
                        LIMIT $1
                    ''', limit)
                return [dict(log) for log in logs]
        except Exception as e:
            logger.error(f"Error getting admin logs: {e}")
            return []
    
    # ==================== SYSTEM SETTINGS ====================
    
    async def get_setting(self, key: str, default: Any = None) -> Any:
        """Get system setting"""
        try:
            async with self.pool.acquire() as conn:
                value = await conn.fetchval('''
                    SELECT setting_value FROM system_settings WHERE setting_key = $1
                ''', key)
                
                if value is None:
                    return default
                
                # Convert based on setting type
                setting_type = await conn.fetchval('''
                    SELECT setting_type FROM system_settings WHERE setting_key = $1
                ''', key)
                
                if setting_type == 'boolean':
                    return value.lower() in ('true', '1', 'yes', 't')
                elif setting_type == 'integer':
                    return int(value)
                elif setting_type == 'float':
                    return float(value)
                elif setting_type == 'json':
                    return json.loads(value)
                else:
                    return value
        except Exception as e:
            logger.error(f"Error getting setting {key}: {e}")
            return default
    
    async def set_setting(self, key: str, value: Any, value_type: str = 'string', 
                         description: str = None, updated_by: int = None) -> bool:
        """Set system setting"""
        try:
            async with self.pool.acquire() as conn:
                # Convert value to string based on type
                if value_type == 'json':
                    value_str = json.dumps(value)
                else:
                    value_str = str(value)
                
                await conn.execute('''
                    INSERT INTO system_settings 
                    (setting_key, setting_value, setting_type, description, updated_by)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (setting_key) DO UPDATE 
                    SET setting_value = EXCLUDED.setting_value,
                        setting_type = EXCLUDED.setting_type,
                        description = EXCLUDED.description,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = CURRENT_TIMESTAMP
                ''', key, value_str, value_type, description, updated_by)
                return True
        except Exception as e:
            logger.error(f"Error setting setting {key}: {e}")
            return False
    
    # ==================== CLEANUP & MAINTENANCE ====================
    
    async def cleanup_expired_subscriptions(self) -> int:
        """Deactivate expired subscriptions"""
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval('''
                    WITH updated AS (
                        UPDATE subscriptions 
                        SET is_active = FALSE 
                        WHERE is_active = TRUE AND expiry_date < CURRENT_TIMESTAMP
                        RETURNING 1
                    )
                    SELECT COUNT(*) FROM updated
                ''')
                return count
        except Exception as e:
            logger.error(f"Error cleaning up expired subscriptions: {e}")
            return 0
    
    async def cleanup_old_logs(self, days: int = 90) -> int:
        """Delete old logs"""
        try:
            async with self.pool.acquire() as conn:
                # Clean admin logs
                admin_count = await conn.fetchval('''
                    DELETE FROM admin_logs 
                    WHERE timestamp < CURRENT_TIMESTAMP - INTERVAL '$1 days'
                    RETURNING 1
                ''', days)
                
                # Clean user logs
                user_count = await conn.fetchval('''
                    DELETE FROM user_logs 
                    WHERE timestamp < CURRENT_TIMESTAMP - INTERVAL '$1 days'
                    RETURNING 1
                ''', days)
                
                # Clean file access logs
                file_count = await conn.fetchval('''
                    DELETE FROM file_access_logs 
                    WHERE accessed_at < CURRENT_TIMESTAMP - INTERVAL '$1 days'
                    RETURNING 1
                ''', days)
                
                return (admin_count or 0) + (user_count or 0) + (file_count or 0)
        except Exception as e:
            logger.error(f"Error cleaning up old logs: {e}")
            return 0
    
    async def cleanup_old_tickets(self, days: int = 30) -> int:
        """Delete old completed/failed tickets"""
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval('''
                    DELETE FROM payment_tickets 
                    WHERE status IN ('completed', 'failed')
                    AND created_at < CURRENT_TIMESTAMP - INTERVAL '$1 days'
                    RETURNING 1
                ''', days)
                return count or 0
        except Exception as e:
            logger.error(f"Error cleaning up old tickets: {e}")
            return 0
    
    # ==================== BACKUP & EXPORT ====================
    
    async def export_data(self, table_name: str, limit: int = 1000) -> List[Dict]:
        """Export data from a table"""
        try:
            async with self.pool.acquire() as conn:
                data = await conn.fetch(f'''
                    SELECT * FROM {table_name} 
                    ORDER BY 1 
                    LIMIT $1
                ''', limit)
                return [dict(row) for row in data]
        except Exception as e:
            logger.error(f"Error exporting data from {table_name}: {e}")
            return []
    
    async def get_all_tables(self) -> List[str]:
        """Get all table names"""
        try:
            async with self.pool.acquire() as conn:
                tables = await conn.fetch('''
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                ''')
                return [table['table_name'] for table in tables]
        except Exception as e:
            logger.error(f"Error getting table names: {e}")
            return []
    
    # ==================== UTILITY METHODS ====================
    
    async def close(self):
        """Close database connection"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection closed")
    
    async def execute_query(self, query: str, *args) -> Any:
        """Execute raw SQL query"""
        try:
            async with self.pool.acquire() as conn:
                if query.strip().upper().startswith('SELECT'):
                    result = await conn.fetch(query, *args)
                    return [dict(row) for row in result]
                else:
                    result = await conn.execute(query, *args)
                    return result
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            raise
    
    async def ping(self) -> bool:
        """Check database connection"""
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval('SELECT 1')
                return result == 1
        except Exception as e:
            logger.error(f"Database ping failed: {e}")
            return False

# Global database instance
db_instance = Database()

async def get_db():
    """Get database instance (for dependency injection)"""
    return db_instance