import psycopg2

# Connect to the database
conn = psycopg2.connect(
    host="localhost",
    database="ai_karen",
    user="karen_user",
    password="karen_secure_pass_change_me",
)

# Update the admin user's password hash
cursor = conn.cursor()
cursor.execute("""
    UPDATE auth_users
    SET password_hash = '$2b$12$76OItNxTd1aLq5eGSSCBReJtsICNWSJVblEKOHneTYMfh.pBZHSDu'
    WHERE email = 'admin@karen.ai'
""")

conn.commit()
cursor.close()
conn.close()

print("Admin user password updated successfully!")
