import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.records import RecordRepository
from ..schemas import RecordCreate, RecordFilter

logger = logging.getLogger(__name__)


class RecordService:
    def __init__(self, session: AsyncSession, telegram_id: int):
        self.repo = RecordRepository(session)
        self.telegram_id = telegram_id

    async def add(self, data: RecordCreate, *, allow_duplicate: bool = False):
        logger.info(f"RecordService.add() called for telegram_id={self.telegram_id}")
        try:
            record = await self.repo.add_record(
                self.telegram_id,
                data,
                allow_duplicate=allow_duplicate,
            )
            logger.info(f"Record successfully added: id={record.id}")
            return record
        except ValueError as e:
            logger.error(f"Validation error: {e}")
            raise

    async def list(self, filters: RecordFilter | None = None, limit: int = 100, offset: int = 0):
        logger.info(f"RecordService.list() called with limit={limit}, offset={offset}")
        records = await self.repo.list_records(self.telegram_id, filters, limit=limit, offset=offset)
        logger.info(f"Listed {len(records)} records")
        return records

    async def count(self, filters: RecordFilter | None = None) -> int:
        return await self.repo.count_records(self.telegram_id, filters)

    async def get(self, record_id: int):
        return await self.repo.get_record(self.telegram_id, record_id)

    async def update(self, record_id: int, data: RecordCreate):
        logger.info("RecordService.update() called for record_id=%s", record_id)
        return await self.repo.update_record(self.telegram_id, record_id, data)

    async def delete(self, record_id: int) -> bool:
        logger.info("RecordService.delete() called for record_id=%s", record_id)
        return await self.repo.delete_record(self.telegram_id, record_id)
