import base64
import os

# Generate 32 random bytes
random_bytes = os.urandom(32)
# Encode to base64
key = base64.urlsafe_b64encode(random_bytes).decode()
print(f"Generated key: {key}")
print(f"Length: {len(key)} characters")
