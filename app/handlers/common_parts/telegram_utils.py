from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from .constants import TELEGRAM_MIN_CHUNK_LIMIT, TELEGRAM_SAFE_TEXT_LIMIT


def split_message_chunks(text: str, chunk_size: int = TELEGRAM_SAFE_TEXT_LIMIT) -> list[str]:
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        line_len = len(line)

        if line_len > chunk_size:
            if current:
                chunks.append("".join(current).rstrip("\n"))
                current = []
                current_len = 0

            for start in range(0, line_len, chunk_size):
                part = line[start : start + chunk_size]
                chunks.append(part.rstrip("\n"))
            continue

        if current_len + line_len > chunk_size and current:
            chunks.append("".join(current).rstrip("\n"))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("".join(current).rstrip("\n"))

    return [chunk for chunk in chunks if chunk]


async def answer_chunked(message: Message, text: str, chunk_size: int = TELEGRAM_SAFE_TEXT_LIMIT) -> None:
    queue = split_message_chunks(text, chunk_size=chunk_size)
    while queue:
        chunk = queue.pop(0)
        try:
            await message.answer(chunk)
        except TelegramBadRequest as exc:
            error_text = str(exc).lower()
            if "message is too long" not in error_text:
                raise

            if len(chunk) <= TELEGRAM_MIN_CHUNK_LIMIT:
                raise

            smaller_size = max(TELEGRAM_MIN_CHUNK_LIMIT, len(chunk) // 2)
            queue = split_message_chunks(chunk, chunk_size=smaller_size) + queue


async def safe_edit_callback_message(callback: CallbackQuery, text: str, reply_markup=None) -> bool:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)  # type: ignore
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return False
        raise
