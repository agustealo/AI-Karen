
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

password = "Admin@123!"
hash = "$2b$12$ibSgfSzD0sdgzbheQ8NUxOurD3kyYEukqQpzClhVlh2YsWdJ5T1E2"

result = pwd_context.verify(password, hash)
print(f"Match: {result}")
