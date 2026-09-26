import os
import asyncio
import threading
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetPollVotesRequest
from fastapi import FastAPI
import uvicorn

# --- Веб-сервер заглушка для Render ---
app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "alive"}

# Уникальный скрытый маршрут для предотвращения засыпания
@app.get("/healthz_bot_ping")
def keep_alive():
    return {"status": "ok", "worker": "active"}

def run_web_server():
    # Render сам передаст нужный порт в переменную PORT
    port = int(os.environ.get("PORT", 10000))
    print(f"Запуск веб-сервера заглушки на порту {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)

# --- основной код воркера Telegram + Firebase ---
KEY_PATH = "/etc/secrets/firebase_key.json" if os.path.exists("/etc/secrets/firebase_key.json") else "firebase_key.json"

if not firebase_admin._apps:
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
USERBOT_SESSION = os.environ.get("USERBOT_SESSION", "")

client = TelegramClient(StringSession(USERBOT_SESSION), API_ID, API_HASH)

async def process_job(job_id: str, data: dict):
    chat_id = data.get('chat_id')
    message_id = data.get('message_id')
    voter_ids = set()

    try:
        entity = await client.get_entity(chat_id)
        message = await client.get_messages(entity, ids=message_id)
        
        if message and message.poll:
            poll_options = message.poll.poll.answers
            for option in poll_options:
                result = await client(GetPollVotesRequest(
                    peer=entity,
                    id=message_id,
                    option=option.option,
                    limit=100
                ))
                
                for vote in result.votes:
                    if hasattr(vote, 'peer') and hasattr(vote.peer, 'user_id'):
                        voter_ids.add(vote.peer.user_id)

        # Отправляем результат обратно в базу
        db.collection('poll_jobs').document(job_id).update({
            'status': 'completed',
            'voters': list(voter_ids)
        })
        print(f"✅ Задача {job_id} успешно выполнена.")
        
    except Exception as e:
        print(f"❌ Ошибка в задаче {job_id}: {e}")
        db.collection('poll_jobs').document(job_id).update({'status': 'error'})

async def worker_loop():
    await client.connect()
    if not await client.is_user_authorized():
        print("Критическая ошибка: Сессия юзербота не авторизована!")
        return

    print("Воркер запущен. Ожидание задач из Firebase...")
    
    while True:
        try:
            # Исправлено предупреждение Firestore (используем FieldFilter)
            docs = db.collection('poll_jobs').where(filter=FieldFilter('status', '==', 'pending')).limit(3).stream()
            for doc in docs:
                db.collection('poll_jobs').document(doc.id).update({'status': 'processing'})
                await process_job(doc.id, doc.to_dict())
        except Exception as e:
            print(f"Ошибка опроса Firebase: {e}")
        
        await asyncio.sleep(2.5)


# --- Точка запуска ---
if __name__ == "__main__":
    # 1. Запускаем веб-сервер в отдельном фоновом потоке
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # 2. Запускаем ваш основной цикл воркера в главном потоке
    asyncio.run(worker_loop())
