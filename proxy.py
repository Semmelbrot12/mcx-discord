# DO NOT EDIT | PROXY FOR BREADZONEMC.NET USER SERVICE
import os
import asyncio
import aiohttp
import json
import aiomysql
from fastapi import FastAPI, HTTPException, Request, Response

# --- CONFIGURATION ---
DB_CONFIG = {
    'host': 'hypnotic.dathost.net',
    'user': 'Z1b1qwrCrMjeubsY',
    'password': 'PU7N__qqXQI',
    'db': '6756f5ab0ac2acc8deb9bb18',
    'charset': 'utf8mb4'
}

# This is where the FastAPI app must be defined
app = FastAPI()

# Now the middleware can be registered, because 'app' exists.
@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"Incoming request: {request.method} {request.url}")
    print(f"Client IP: {request.client.host}")
    
    response = await call_next(request)
    
    print(f"Outgoing response: {response.status_code}")
    return response

# You would remove this logging middleware in production to avoid cluttering your logs.

# --- API ENDPOINTS ---
@app.get('/skins/{uuid}.png')
async def get_skin_data(uuid: str):
    """
    Fetches a skin from an external API and returns the image data.
    """
    url = f"https://crafatar.com/avatars/{uuid}?size=80&overlay"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    image_data = await response.read()
                    return Response(content=image_data, media_type="image/png")
                else:
                    raise HTTPException(status_code=response.status, detail="Failed to fetch skin from external API.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")

@app.post("/friends/send_request")
async def send_friend_request(request: Request):
    data = await request.json()
    current_user = data.get('current_user')
    target_user = data.get('target_user')

    if not current_user or not target_user:
        raise HTTPException(status_code=400, detail="Missing user information.")

    async with aiomysql.create_pool(**DB_CONFIG) as pool:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Get the target user's current friends, blocked, and pending lists
                await cur.execute("SELECT friends, blocked_users, pending_friend_requests FROM nlogin WHERE last_name=%s", (target_user,))
                target_data = await cur.fetchone()
                
                # Get the current user's friends list
                await cur.execute("SELECT friends FROM nlogin WHERE last_name=%s", (current_user,))
                my_friends_data = await cur.fetchone()

                if not target_data or not my_friends_data:
                    raise HTTPException(status_code=404, detail="User not found.")

                target_friends, target_blocked, target_pending = target_data
                my_friends = json.loads(my_friends_data[0] or '[]')

                target_pending_list = json.loads(target_pending or '[]')
                target_blocked_list = json.loads(target_blocked or '[]')

                # Check for existing relationship before sending
                if current_user in target_blocked_list or target_user in my_friends:
                    raise HTTPException(status_code=409, detail="Cannot send request. Existing relationship or blocked.")

                if current_user not in target_pending_list:
                    target_pending_list.append(current_user)
                    await cur.execute("UPDATE nlogin SET pending_friend_requests=%s WHERE last_name=%s", (json.dumps(target_pending_list), target_user))
                    await conn.commit()
                    return {"message": "Friend request sent."}
                else:
                    raise HTTPException(status_code=409, detail="Friend request already pending.")

@app.post("/friends/accept_request")
async def accept_friend_request(request: Request):
    data = await request.json()
    current_user = data.get('current_user')
    target_user = data.get('target_user')

    async with aiomysql.create_pool(**DB_CONFIG) as pool:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Get both users' data
                await cur.execute("SELECT friends, pending_friend_requests FROM nlogin WHERE last_name=%s", (current_user,))
                my_data = await cur.fetchone()
                
                await cur.execute("SELECT friends FROM nlogin WHERE last_name=%s", (target_user,))
                target_data = await cur.fetchone()

                my_friends_list = json.loads(my_data[0] or '[]')
                my_pending_list = json.loads(my_data[1] or '[]')
                target_friends_list = json.loads(target_data[0] or '[]')

                if target_user in my_pending_list:
                    # Update current user
                    my_pending_list.remove(target_user)
                    my_friends_list.append(target_user)
                    await cur.execute("UPDATE nlogin SET friends=%s, pending_friend_requests=%s WHERE last_name=%s", (json.dumps(my_friends_list), json.dumps(my_pending_list), current_user))
                    
                    # Update target user
                    target_friends_list.append(current_user)
                    await cur.execute("UPDATE nlogin SET friends=%s WHERE last_name=%s", (json.dumps(target_friends_list), target_user))
                    
                    await conn.commit()
                    return {"message": "Friend request accepted."}
                else:
                    raise HTTPException(status_code=409, detail="No pending request from this user.")

@app.post("/friends/reject_request")
async def reject_friend_request(request: Request):
    data = await request.json()
    current_user = data.get('current_user')
    target_user = data.get('target_user')

    async with aiomysql.create_pool(**DB_CONFIG) as pool:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT pending_friend_requests FROM nlogin WHERE last_name=%s", (current_user,))
                pending_requests_data = await cur.fetchone()
                
                pending_list = json.loads(pending_requests_data[0] or '[]')
                
                if target_user in pending_list:
                    pending_list.remove(target_user)
                    await cur.execute("UPDATE nlogin SET pending_friend_requests=%s WHERE last_name=%s", (json.dumps(pending_list), current_user))
                    await conn.commit()
                    return {"message": "Friend request rejected."}
                else:
                    raise HTTPException(status_code=409, detail="No pending request from this user.")

@app.post("/friends/block")
async def block_user(request: Request):
    data = await request.json()
    current_user = data.get('current_user')
    target_user = data.get('target_user')

    async with aiomysql.create_pool(**DB_CONFIG) as pool:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT friends, blocked_users FROM nlogin WHERE last_name=%s", (current_user,))
                my_data = await cur.fetchone()
                
                my_friends_list = json.loads(my_data[0] or '[]')
                my_blocked_list = json.loads(my_data[1] or '[]')

                if target_user not in my_blocked_list:
                    my_blocked_list.append(target_user)
                    # Also remove them from friends list if they exist
                    if target_user in my_friends_list:
                        my_friends_list.remove(target_user)
                    
                    await cur.execute("UPDATE nlogin SET friends=%s, blocked_users=%s WHERE last_name=%s", (json.dumps(my_friends_list), json.dumps(my_blocked_list), current_user))
                    await conn.commit()
                    return {"message": "User blocked."}
                else:
                    raise HTTPException(status_code=409, detail="User is already blocked.")

@app.post("/friends/unblock")
async def unblock_user(request: Request):
    data = await request.json()
    current_user = data.get('current_user')
    target_user = data.get('target_user')

    async with aiomysql.create_pool(**DB_CONFIG) as pool:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT blocked_users FROM nlogin WHERE last_name=%s", (current_user,))
                my_data = await cur.fetchone()
                
                my_blocked_list = json.loads(my_data[0] or '[]')

                if target_user in my_blocked_list:
                    my_blocked_list.remove(target_user)
                    await cur.execute("UPDATE nlogin SET blocked_users=%s WHERE last_name=%s", (json.dumps(my_blocked_list), current_user))
                    await conn.commit()
                    return {"message": "User unblocked."}
                else:
                    raise HTTPException(status_code=409, detail="User is not in your blocked list.")
