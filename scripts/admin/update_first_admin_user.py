import asyncio
import asyncpg
import bcrypt

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@127.0.0.1:54322/postgres')
    password_hash = bcrypt.hashpw(b'!Password123', bcrypt.gensalt()).decode('utf-8')
    
    query = """
    UPDATE auth_users
    SET email = $1,
        password_hash = $2,
        is_active = true,
        is_verified = true,
        updated_at = now()
    WHERE username = $3 OR email = $4 OR email = $1;
    """
    
    res = await conn.execute(query, 'admin@karen.ai', password_hash, 'admin', 'admin@kari.ai')
    print('Update status:', res)
    
    rows = await conn.fetch('SELECT user_id, email, username, roles, is_active, is_verified FROM auth_users;')
    print('\nCurrent Users in auth_users:')
    for r in rows:
        print(dict(r))
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
