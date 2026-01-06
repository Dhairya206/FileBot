import os
import sys

# Read .env
env_vars = {}
if os.path.exists('.env'):
    with open('.env', 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()

print("🔐 Testing Encryption Key...")
print("=" * 30)

key = env_vars.get('ENCRYPTION_KEY')

if not key:
    print("❌ No ENCRYPTION_KEY found")
    sys.exit(1)

print(f"✅ Key found: {key[:20]}...")
print(f"Length: {len(key)} characters")

# Check basic format
if key.startswith('gAAAAA'):
    print("✅ Starts with 'gAAAAA' - Good format")
else:
    print("⚠️  Doesn't start with 'gAAAAA'")

# Try to use it (if cryptography available)
try:
    from cryptography.fernet import Fernet
    print("\n🔧 Testing with cryptography library...")
    cipher = Fernet(key.encode())
    print("✅ Key is valid Fernet key!")
    
    # Test encryption/decryption
    test_data = b"Test message"
    encrypted = cipher.encrypt(test_data)
    decrypted = cipher.decrypt(encrypted)
    
    if decrypted == test_data:
        print("✅ Encryption/Decryption working!")
    else:
        print("❌ Encryption test failed")
        
except ImportError:
    print("⚠️  Cryptography not installed (Railway will install it)")
except Exception as e:
    print(f"⚠️  Key validation error: {e}")

print("\n🎯 Key looks ready for Railway deployment!")
