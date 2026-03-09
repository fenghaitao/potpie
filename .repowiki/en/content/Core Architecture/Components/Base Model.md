# Base Model

The **Base Model** serves as the foundation of the database architecture, providing a shared class structure for defining database entities.

## Purpose

- Serves as the base class (`Base`) for all SQLAlchemy ORM models.
- Automatically generates table names for models derived from it by converting class names to lowercase.
- Ensures consistent handling of `id` across all models.

## Implementation

The `Base` class is structured as follows:
```python
from sqlalchemy.ext.declarative import as_declarative, declared_attr
from typing import Any, Dict

class_registry: Dict = {}

@as_declarative(class_registry=class_registry)
class Base:
    id: Any
    __name__: str

    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()
```

## Key Features

1. **Class Registry:**
   - Helps manage and track all registered ORM classes.
2. **Automatic Table Names:**
   - No need to define the `__tablename__` property manually in derived classes; names will be automatically generated.

## Usage

All ORM models should inherit from `Base` to ensure uniform table naming and shared behavior.

---