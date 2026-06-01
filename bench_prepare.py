import asyncio
import time
from app.db import get_session
from app.handlers.common import _prepare_classifier

async def main():
    async with get_session() as session:
        t = time.time()
        await _prepare_classifier(session, 886332747)
        print('first_prepare_sec', round(time.time() - t, 3))

        t = time.time()
        await _prepare_classifier(session, 886332747)
        print('second_prepare_sec', round(time.time() - t, 3))

asyncio.run(main())
