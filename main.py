import os
import asyncio
from fastapi import FastAPI, HTTPException
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetPollVotesRequest

app = FastAPI()

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
USERBOT_SESSION = os.environ.get("USERBOT_SESSION", "")

client = TelegramClient(StringSession(USERBOT_SESSION), API_ID, API_HASH)

@app.on_event("startup")
async def startup_event():
    if API_ID and API_HASH and USERBOT_SESSION:
        await client.connect()

@app.on_event("shutdown")
async def shutdown_event():
    await client.disconnect()

@app.get("/get_votes")
async def get_votes(chat_id: int, message_id: int):
    if not await client.is_user_authorized():
        raise HTTPException(status_code=500, detail="Userbot is not authorized")

    voter_ids = set()
    try:
        entity = await client.get_entity(chat_id)
        message = await client.get_messages(entity, ids=message_id)
        
        if not message or not message.poll:
            return {"voters": []}

        poll_options = message.poll.poll.answers

        for option in poll_options:
            result = await client(GetPollVotesRequest(
                peer=entity,
                id=message_id,
                option=option.option,
                limit=100
            ))
            for vote in result.votes:
                voter_ids.add(vote.user_id)

        return {"voters": list(voter_ids)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))