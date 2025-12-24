"""
Generate a secure SECRET_KEY for production use
Run this script and copy the output to your .env file
"""

import secrets

# Generate a secure random key
secret_key = secrets.token_hex(32)

print("=" * 60)
print("PRODUCTION SECRET KEY")
print("=" * 60)
print()
print("Copy this key to your .env file:")
print()
print(f"SECRET_KEY={secret_key}")
print()
print("=" * 60)
print()
print("⚠️  IMPORTANT:")
print("   - Keep this key secret!")
print("   - Never commit it to version control")
print("   - Use different keys for dev/staging/production")
print()
print("=" * 60)
