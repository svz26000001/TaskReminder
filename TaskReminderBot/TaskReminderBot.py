TOKEN = "8372571348:AAFzMByt_FgK-pkRZNYVB7AziwfwOpvDZM0"
OPENAI_KEY = "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"

import asyncio
import json
import datetime
import aiosqlite
from pytz import timezone
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import CommandStart
from openai import OpenAI


bot = Bot(token=TOKEN)
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_KEY)

tz = timezone("Europe/Kyiv")

DB_FILE = "reminders.db"


# ============================
# Database
# ============================

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            text TEXT,
            remind_time REAL,
            status INTEGER DEFAULT 0
        )
        """)
        await db.commit()


async def add_reminder(chat_id, text, remind_ts):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO reminders(chat_id,text,remind_time) VALUES(?,?,?)",
            (chat_id, text, remind_ts)
        )
        await db.commit()


async def get_pending_reminders():
    now_ts = datetime.datetime.now(tz).timestamp()

    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute(
            "SELECT id, chat_id, text FROM reminders "
            "WHERE remind_time <= ? AND status = 0",
            (now_ts,)
        )
        return await cursor.fetchall()


async def mark_done(reminder_id):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "UPDATE reminders SET status = 1 WHERE id = ?",
            (reminder_id,)
        )
        await db.commit()


# ============================
# Background Worker
# ============================

async def reminder_worker():
    while True:
        reminders = await get_pending_reminders()

        for rid, chat_id, text in reminders:
            try:
                await bot.send_message(
                    chat_id,
                    f"Нагадування: {text}"
                )
                await mark_done(rid)
            except:
                pass

        await asyncio.sleep(5)


# ============================
# Handlers
# ============================

@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer("Запиши голосове повідомлення з нагадуванням.")


@dp.message()
async def voice_handler(message: Message):
    if not message.voice:
        return await message.answer("Надішли голосове повідомлення.")

    file = await bot.get_file(message.voice.file_id)
    await bot.download_file(file.file_path, "voice.ogg")

    # Whisper transcription
    with open("voice.ogg", "rb") as audio:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio
        )

    text = transcript.text

    now = datetime.datetime.now(tz)
    current_time_str = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    # GPT parsing
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system",
                "content": f"""
                Текущая дата и время: {current_time_str}

                Верни JSON:
                {{
                  "task": "...",
                  "datetime": "YYYY-MM-DD HH:MM:SS"
                }}

                Не придумывай дату.
                """
            },
            {"role": "user", "content": text}
        ],
        temperature=0
    )

    try:
        data = json.loads(response.choices[0].message.content)
    except:
        return await message.answer("Ошибка парсинга GPT ответа")

    task_text = data["task"]

    task_time = datetime.datetime.strptime(
        data["datetime"],
        "%Y-%m-%d %H:%M:%S"
    )

    task_time = tz.localize(task_time)

    if task_time.timestamp() < now.timestamp():
        task_time += datetime.timedelta(days=1)

    await add_reminder(
        message.chat.id,
        task_text,
        task_time.timestamp()
    )

    await message.answer(
        f"Нагадування створено: {task_text}\nЧас: {task_time}"
    )


# ============================

async def main():
    await init_db()

    asyncio.create_task(reminder_worker())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())