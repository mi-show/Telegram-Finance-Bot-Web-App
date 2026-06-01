"""
Initialize database and load custom keywords.
Run this once after database is created.
"""
import asyncio

from app.db import Base, engine
from app.scripts.load_custom import ensure_custom_keywords
from app.scripts.sanity_check_seed_keywords import run_seed_sanity_check


async def init_db():
    """Create all tables and load custom keywords."""
    print("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Tables created.")

    print("Running seed keyword sanity check...")
    errors, warnings = run_seed_sanity_check()
    for warning in warnings[:20]:
        print(f"WARN: {warning}")
    if errors:
        for error in errors[:20]:
            print(f"ERR: {error}")
        raise RuntimeError(f"Seed keyword sanity check failed with {len(errors)} errors")
    print("✓ Seed keyword sanity check passed.")

    print("Loading custom keywords...")
    try:
        await ensure_custom_keywords()
        print(f"✓ Keywords loaded.")
    except Exception as e:
        print(f"✗ Error loading keywords: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(init_db())
