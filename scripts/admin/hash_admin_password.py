import bcrypt

# Generate bcrypt hash for "Admin@123!"
password = "Admin@123!"
salt = bcrypt.gensalt(rounds=12)
hashed = bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

print(f"Password: {password}")
print(f"BCrypt Hash: {hashed}")
