# Base Store

The **Base Store** aids in the management of database sessions, making it easier to transition from synchronous to asynchronous operations.

---

## Purpose

- Provides an abstract store for interacting with both synchronous (`db`) and asynchronous (`async_db`) database sessions.
- Simplifies database operations during the transition to fully asynchronous workflows.

## Implementation
```python
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

class BaseStore:
    """
    A base class for all data stores that holds the database sessions
    needed during the sync-to-async migration period.
    """

    def __init__(self, db: Session, async_db: AsyncSession):
        self.db = db  # For legacy sync dependencies
        self.async_db = async_db  # For new async queries
```

## Key Features

1. **Dual Session Support:**
   - Stores both `Session` (synchronous) and `AsyncSession` (asynchronous).
2. **Backward Compatibility:**
   - Enables easy migration by supporting older synchronous dependencies.
3. **Example Usage:**
```python
store = BaseStore(db_session, async_session)
# Sync usage
query = store.db.query(YourModel).all()
# Async usage
results = await store.async_db.execute(your_query)
```

---