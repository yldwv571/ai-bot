import asyncio
import base64
import io
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from anthropic import AsyncAnthropic

# Kalitlarni muhit o'zgaruvchisidan olamiz (kodga yozib qo'ymang!)
BOT_TOKEN = os.environ["BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["CLAUDE_TOKEN"]

MODEL = "claude-sonnet-5-5"
MAX_HISTORY = 20
SYSTEM_PROMPT = (
    "Sen foydalanuvchiga yordam beradigan do'stona AI yordamchisan. "
    "Foydalanuvchi qaysi tilda yozsa, shu tilda javob ber."
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# {user_id: [{"role": "user"/"assistant", "content": ...}]}
histories: dict[int, list[dict]] = {}
# Bir foydalanuvchining xabarlari ketma-ket ishlashi uchun
locks: dict[int, asyncio.Lock] = {}


def trim(history: list[dict]) -> None:
    del history[:-MAX_HISTORY]
    while history and history[0]["role"] != "user":
        history.pop(0)


async def ask_claude(message: Message, content, text_for_history: str) -> None:
    user_id = message.from_user.id
    lock = locks.setdefault(user_id, asyncio.Lock())

    async with lock:
        history = histories.setdefault(user_id, [])
        history.append({"role": "user", "content": content})
        trim(history)

        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=1000,
                system=SYSTEM_PROMPT,
                messages=history,
            )
            answer = "".join(b.text for b in response.content if b.type == "text")
        except Exception:
            logging.exception("Claude API xatosi")
            history.pop()
            await message.answer("Xatolik yuz berdi, keyinroq urinib ko'ring.")
            return

        # Xotirani tejash uchun tarixda rasm o'rniga matn qoldiramiz
        history[-1] = {"role": "user", "content": text_for_history}
        history.append({"role": "assistant", "content": answer})

    for i in range(0, len(answer), 4000):
        await message.answer(answer[i : i + 4000], parse_mode=None)


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Salom! Men AI botman. Savol yozing yoki rasm yuboring.\n"
        "/reset - suhbatni tozalash"
    )


@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    histories.pop(message.from_user.id, None)
    await message.answer("Suhbat tozalandi.")


@dp.message(F.photo)
async def on_photo(message: Message):
    buf = io.BytesIO()
    await bot.download(message.photo[-1], destination=buf)
    image_b64 = base64.standard_b64encode(buf.getvalue()).decode()

    caption = message.caption or "Bu rasmda nima bor?"
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": image_b64,
            },
        },
        {"type": "text", "text": caption},
    ]
    await ask_claude(message, content, f"[Rasm yuborildi] {caption}")


@dp.message(F.text)
async def on_text(message: Message):
    await ask_claude(message, message.text, message.text)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
