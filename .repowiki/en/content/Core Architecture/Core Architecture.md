# Core Architecture

The **Core Architecture** of the system is built upon key components that ensure the structure and functionality of the entire project. Below is a detailed overview of these components:

## 1. Base Model

- **File:** `base_model.py`
- **Purpose:** Defines the foundational class (`Base`) for all database models used in the system. It utilizes SQLAlchemy's ORM capabilities and provides a mechanism to automatically generate database table names based on class names.
  - **Class Registry:** Ensures uniqueness and management of ORM classes.
  - **Auto Generated Table Names:** Converts class names to lowercase table names.

---

## 2. Base Store

- **File:** `base_store.py`
- **Purpose:** Provides a base class for managing database interactions during the transition from synchronous to asynchronous operations.
  - Stores both synchronous and asynchronous database sessions.
  - Facilitates backward compatibility during migration.

---

## 3. Configuration Provider

- **File:** `config_provider.py`
- **Purpose:** Manages application configurations for various services, including Neo4j, GitHub, object storage, Redis, and code providers.
  - **Environment Variable Management:** Loads configurations dynamically from `.env` files or system variables.
  - **Neo4j Override Capability:** Allows runtime updates for Neo4j configuration.
  - **Object Storage:** Provides strategies for different storage backends (S3, GCS, Azure).
  - **Rate Limiting Tokens:** Manages token pools for external code providers to optimize usage.

---

## 4. Database Management

- **File:** `database.py`
- **Purpose:** Implements both synchronous and asynchronous database connection management.
  - **Engines:** Configured for PostgreSQL, supporting modern database strategies like connection pooling and async models.
  - **Session Management:** Dependency injections for database access in API routes.
  - **Celery Compatibility:** Provides specialized sessions for Celery tasks.

---

## 5. Models

- **File:** `models.py`
- **Purpose:** Central repository of models representing various database tables in the system. These are used across distinct modules such as Media, User, Conversations, and Integrations.
  - Includes high-level entities like `User`, `Conversation`, `Project`, `Task`, etc., along with their interrelations.

---

## 6. Storage Strategies

- **File:** `storage_strategies.py`
- **Purpose:** Defines an extensible strategy pattern for managing storage backends.
  - **Supported Providers:**
    - AWS S3
    - Google Cloud Storage (GCS)
    - Azure Blob Storage (planned support).
  - **Readiness Checks:** Validates the configuration environment before allowing operations.
  - **Dynamic Descriptors:** Configurations for seamless integration with respective storage ecosystems.

---

This modular design ensures extensibility, maintainability, and integration across the different parts of the system.