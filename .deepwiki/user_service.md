7.5-User Service

# Page: User Service

# User Service

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [app/modules/users/user_controller.py](app/modules/users/user_controller.py)
- [app/modules/users/user_router.py](app/modules/users/user_router.py)
- [app/modules/users/user_service.py](app/modules/users/user_service.py)

</details>



The User Service provides core user management functionality for Potpie, including CRUD operations on user records, profile management, onboarding data storage, and last login tracking. This service acts as the data access layer for user-related operations and integrates with Firebase Auth for profile information.

**Scope**: This document covers user lifecycle management, profile retrieval, and onboarding data storage. For authentication and login flows, see [Multi-Provider Authentication](#7.1). For OAuth token management and provider linking, see [OAuth and Provider Linking](#7.3) and [Token Management and Security](#7.4).

## Architecture Overview

The User Service follows a three-layer architecture pattern with a router, controller, and service layer, all interacting with PostgreSQL for user data persistence and Firebase Auth for profile information.

```mermaid
graph TB
    subgraph "API Layer"
        UserAPI["UserAPI<br/>(user_router.py)"]
        GetProfile["/user/{user_id}/public-profile<br/>GET endpoint"]
        PostOnboarding["/user/onboarding<br/>POST endpoint"]
    end
    
    subgraph "Controller Layer"
        UserController["UserController<br/>(user_controller.py)"]
    end
    
    subgraph "Service Layer"
        UserService["UserService<br/>(user_service.py)"]
        UpdateLastLogin["update_last_login()"]
        CreateUser["create_user()"]
        GetUserByUid["get_user_by_uid()"]
        GetUserByEmail["get_user_by_email()"]
        GetUserProfilePic["get_user_profile_pic()"]
        GetUserIdsByEmails["get_user_ids_by_emails()"]
        SetupDummyUser["setup_dummy_user()"]
    end
    
    subgraph "Data Layer"
        UserModel["User Model<br/>(user_model.py)"]
        PostgresDB[("PostgreSQL<br/>User Table")]
    end
    
    subgraph "External Services"
        FirebaseAuth["Firebase Auth<br/>auth.get_user()"]
        Firestore["Firestore<br/>users collection"]
    end
    
    subgraph "Authentication"
        AuthService["AuthService.check_auth<br/>Token Validation"]
    end
    
    GetProfile --> UserAPI
    PostOnboarding --> UserAPI
    UserAPI --> AuthService
    UserAPI --> UserController
    
    UserController --> UserService
    
    UserService --> UpdateLastLogin
    UserService --> CreateUser
    UserService --> GetUserByUid
    UserService --> GetUserByEmail
    UserService --> GetUserProfilePic
    UserService --> GetUserIdsByEmails
    UserService --> SetupDummyUser
    
    UpdateLastLogin --> UserModel
    CreateUser --> UserModel
    GetUserByUid --> UserModel
    GetUserByEmail --> UserModel
    
    UserModel --> PostgresDB
    GetUserProfilePic --> FirebaseAuth
    PostOnboarding --> Firestore
```

**Sources**: [app/modules/users/user_router.py:1-91](), [app/modules/users/user_controller.py:1-16](), [app/modules/users/user_service.py:1-177]()

## User Model and Data Structure

The `User` model in PostgreSQL stores core user information. The table schema includes:

| Field | Type | Description |
|-------|------|-------------|
| `uid` | String (Primary Key) | Firebase UID or provider-specific user ID |
| `email` | String | User's email address |
| `display_name` | String | User's display name |
| `email_verified` | Boolean | Email verification status |
| `created_at` | DateTime | Account creation timestamp |
| `last_login_at` | DateTime | Last login timestamp |
| `provider_info` | JSON | OAuth tokens and provider metadata |
| `provider_username` | String | Username from OAuth provider |

The `provider_info` JSON field stores OAuth access tokens and other provider-specific data. This field is updated during login to maintain current authentication credentials.

**Sources**: [app/modules/users/user_service.py:9-10](), [app/modules/users/user_service.py:24-56]()

## UserService Class

The `UserService` class [app/modules/users/user_service.py:20-177]() provides all user data access operations. The service is instantiated with a SQLAlchemy `Session` object for database operations.

### Initialization

```python
UserService(db: Session)
```

The constructor accepts a database session that is used for all subsequent operations. This follows the dependency injection pattern used throughout Potpie.

**Sources**: [app/modules/users/user_service.py:21-22]()

### Core CRUD Operations

#### User Creation

```mermaid
graph LR
    CreateUserInput["CreateUser Schema<br/>uid, email, display_name,<br/>provider_info, etc."]
    CreateUserMethod["create_user()<br/>user_service.py:58-89"]
    UserModel["User Model Instance"]
    DBCommit["db.add()<br/>db.commit()<br/>db.refresh()"]
    PostgresDB[("PostgreSQL<br/>User Table")]
    Return["Return:<br/>(uid, message, error)"]
    
    CreateUserInput --> CreateUserMethod
    CreateUserMethod --> UserModel
    UserModel --> DBCommit
    DBCommit --> PostgresDB
    DBCommit --> Return
```

The `create_user()` method [app/modules/users/user_service.py:58-89]() accepts a `CreateUser` schema object and performs the following:

1. Creates a new `User` model instance with provided details
2. Adds the user to the database session
3. Commits the transaction
4. Returns a tuple: `(uid, message, error)` indicating success or failure

**Exception Handling**: The method catches all exceptions during database operations and returns an error tuple rather than propagating exceptions.

**Sources**: [app/modules/users/user_service.py:58-89]()

#### User Retrieval

The service provides multiple methods for retrieving users:

| Method | Parameters | Return Type | Description |
|--------|------------|-------------|-------------|
| `get_user_by_uid()` | `uid: str` | `User` or `None` | Retrieves user by Firebase UID |
| `get_user_by_email()` | `email: str` | `User` or `None` | Async method to retrieve user by email |
| `get_user_id_by_email()` | `email: str` | `str` or `None` | Returns only the UID for a given email |
| `get_user_ids_by_emails()` | `emails: List[str]` | `List[str]` or `None` | Bulk retrieval of UIDs from email list |

**Key Implementation Details**:

- `get_user_by_uid()` [app/modules/users/user_service.py:114-120]() performs a simple query filter on the `uid` field
- `get_user_by_email()` [app/modules/users/user_service.py:138-152]() is async and includes comprehensive error handling for `SQLAlchemyError` and general exceptions
- `get_user_ids_by_emails()` [app/modules/users/user_service.py:154-167]() uses SQL `IN` clause for efficient bulk queries

**Sources**: [app/modules/users/user_service.py:114-167]()

#### Last Login Update

The `update_last_login()` method [app/modules/users/user_service.py:24-56]() updates both the login timestamp and OAuth token:

```mermaid
graph TD
    Start["update_last_login(uid, oauth_token)"]
    Query["Query User by uid"]
    CheckExists{User<br/>exists?}
    UpdateTimestamp["Set last_login_at<br/>to datetime.utcnow()"]
    UpdateProvider["Update provider_info<br/>with access_token"]
    SafeCopy["Safely copy provider_info<br/>dict to avoid mutation"]
    Commit["db.commit()<br/>db.refresh()"]
    ReturnSuccess["Return: (message, False)"]
    ReturnError["Return: (error_msg, True)"]
    
    Start --> Query
    Query --> CheckExists
    CheckExists -->|Yes| UpdateTimestamp
    CheckExists -->|No| ReturnError
    UpdateTimestamp --> UpdateProvider
    UpdateProvider --> SafeCopy
    SafeCopy --> Commit
    Commit --> ReturnSuccess
```

**Important Implementation Notes**:
- The method safely handles `None` or non-dict `provider_info` values by creating a new dict [app/modules/users/user_service.py:34-42]()
- It creates a copy of the existing provider info before modification to avoid SQLAlchemy mutation issues
- Returns a tuple `(message, error)` for consistent error handling

**Sources**: [app/modules/users/user_service.py:24-56]()

### Development Mode Support

The `setup_dummy_user()` method [app/modules/users/user_service.py:91-112]() creates a default user for development environments:

1. Reads `defaultUsername` from environment variables
2. Checks if dummy user already exists
3. Creates a dummy user with email `defaultuser@potpie.ai` if not present
4. Uses hardcoded values including `access_token: "dummy_token"` and `provider_username: "self"`

This enables testing without requiring Firebase authentication in development mode.

**Sources**: [app/modules/users/user_service.py:91-112]()

### Profile Picture Retrieval

The `get_user_profile_pic()` method [app/modules/users/user_service.py:169-176]() retrieves profile pictures from Firebase Auth:

```python
async def get_user_profile_pic(uid: str) -> UserProfileResponse
```

**Implementation Flow**:
1. Uses `asyncio.to_thread()` to call Firebase Admin SDK's `auth.get_user()` synchronously
2. Extracts `photo_url` from the Firebase user record
3. Returns `UserProfileResponse` with `user_id` and `profile_pic_url`
4. Returns `None` if any error occurs during retrieval

This method demonstrates integration between Potpie's PostgreSQL-based user management and Firebase Auth's profile data.

**Sources**: [app/modules/users/user_service.py:169-176]()

## UserController Layer

The `UserController` class [app/modules/users/user_controller.py:9-15]() provides a thin coordination layer between the API router and service:

```mermaid
graph LR
    Router["user_router.py<br/>UserAPI"]
    Controller["UserController<br/>user_controller.py"]
    Service["UserService<br/>user_service.py"]
    
    Router -->|"Depends(get_db)"| Controller
    Controller -->|"self.service"| Service
```

The controller is instantiated with a database session and creates a `UserService` instance. Currently, it only exposes one method:

- `get_user_profile_pic(uid: str)` - Delegates to `UserService.get_user_profile_pic()`

This layer exists to support future expansion of business logic that might require coordination between multiple services.

**Sources**: [app/modules/users/user_controller.py:1-16]()

## API Endpoints

The `UserAPI` class [app/modules/users/user_router.py:19-91]() exposes two REST endpoints:

### GET /user/{user_id}/public-profile

Retrieves the user's profile picture URL from Firebase Auth.

```mermaid
graph LR
    Request["GET /user/{user_id}/public-profile"]
    Auth["AuthService.check_auth<br/>Validate token"]
    Controller["UserController"]
    Service["UserService.get_user_profile_pic()"]
    Firebase["Firebase Auth<br/>auth.get_user()"]
    Response["UserProfileResponse<br/>{user_id, profile_pic_url}"]
    
    Request --> Auth
    Auth --> Controller
    Controller --> Service
    Service --> Firebase
    Firebase --> Response
```

**Request Parameters**:
- `user_id` (path): Firebase UID of the user

**Authentication**: Requires valid bearer token via `AuthService.check_auth` dependency

**Response**: `UserProfileResponse` schema with `user_id` and `profile_pic_url` fields

**Sources**: [app/modules/users/user_router.py:20-27]()

### POST /user/onboarding

Saves user onboarding data to Firestore using Firebase Admin SDK.

```mermaid
graph TD
    Request["POST /user/onboarding<br/>OnboardingDataRequest"]
    Auth["AuthService.check_auth"]
    CheckUID{Authenticated UID<br/>matches request UID?}
    GetFirestore["Get Firestore client<br/>firestore.client()"]
    PrepareDoc["Prepare document:<br/>uid, email, name, source,<br/>industry, jobTitle, companyName"]
    SaveDoc["doc_ref.set(user_doc, merge=True)<br/>Collection: users"]
    Success["OnboardingDataResponse<br/>{success: True}"]
    Error403["HTTP 403<br/>UID mismatch"]
    Error500["HTTP 500<br/>Save failure"]
    
    Request --> Auth
    Auth --> CheckUID
    CheckUID -->|No| Error403
    CheckUID -->|Yes| GetFirestore
    GetFirestore --> PrepareDoc
    PrepareDoc --> SaveDoc
    SaveDoc -->|Success| Success
    SaveDoc -->|Exception| Error500
```

**Request Body** (`OnboardingDataRequest`):
- `uid`: User's Firebase UID
- `email`: User's email
- `name`: Display name
- `source`: How user discovered Potpie
- `industry`: User's industry
- `jobTitle`: User's job title
- `companyName`: User's company

**Authorization Logic** [app/modules/users/user_router.py:43-53]():
1. Extracts authenticated UID from token (checks both `uid` and `user_id` keys for compatibility)
2. Verifies that authenticated UID matches the request UID
3. Returns HTTP 403 if mismatch detected

**Firestore Integration** [app/modules/users/user_router.py:56-76]():
- Creates/updates document in `users` collection with key as the user's UID
- Uses `merge=True` to update existing documents without overwriting
- Adds `signedUpAt` timestamp in ISO 8601 format with UTC timezone
- Uses Firebase Admin SDK which has full permissions, bypassing client-side restrictions

**Error Handling**:
- HTTP 403: UID mismatch (user attempting to save data for another user)
- HTTP 500: Any error during Firestore operations

**Sources**: [app/modules/users/user_router.py:29-90]()

## Integration Points

### PostgreSQL Integration

The User Service interacts with the PostgreSQL `User` table for all CRUD operations. Key integration patterns:

1. **Session Management**: All operations use SQLAlchemy `Session` passed during service instantiation
2. **Transaction Handling**: Operations use `db.commit()` for persistence and `db.refresh()` to reload updated data
3. **Query Patterns**: Simple filter queries using SQLAlchemy ORM (e.g., `db.query(User).filter(User.uid == uid).first()`)

**Sources**: [app/modules/users/user_service.py:21-22]()

### Firebase Auth Integration

The service integrates with Firebase Auth in two ways:

1. **Profile Pictures** [app/modules/users/user_service.py:169-176](): Uses `firebase_admin.auth.get_user()` to retrieve profile photo URLs
2. **Onboarding Data** [app/modules/users/user_router.py:56-76](): Uses Firestore client to persist onboarding information

**Async Handling**: Profile picture retrieval wraps synchronous Firebase SDK calls with `asyncio.to_thread()` to avoid blocking the event loop.

**Sources**: [app/modules/users/user_service.py:1-6](), [app/modules/users/user_router.py:56-76]()

### Authentication Service Integration

All API endpoints depend on `AuthService.check_auth` middleware [app/modules/users/user_router.py:23-24]() which:
- Validates bearer tokens
- Sets `request.state.user` with authenticated user context
- Returns HTTP 401 if authentication fails

The onboarding endpoint uses the authenticated user context to enforce UID matching [app/modules/users/user_router.py:43-53]().

**Sources**: [app/modules/users/user_router.py:5](), [app/modules/users/user_router.py:23](), [app/modules/users/user_router.py:32]()

## Error Handling and Logging

The User Service implements consistent error handling patterns:

### Service Layer Error Handling

Service methods use a tuple return pattern for errors:
```python
return (uid, message, error)  # For create operations
return (message, error)       # For update operations
```

This allows callers to check the `error` boolean without catching exceptions.

### Exception Catching

- `get_user_by_email()` [app/modules/users/user_service.py:147-152]() differentiates between `SQLAlchemyError` and general exceptions
- All methods catch broad `Exception` as a fallback and log errors using the configured logger
- No exceptions propagate to callers; all errors are logged and returned as error tuples or `None`

### Logging

The service uses `setup_logger(__name__)` [app/modules/users/user_router.py:16]() and [app/modules/users/user_service.py:13]() for consistent logging:

- **Info logs**: User creation, login updates, query operations
- **Warning logs**: User not found scenarios, UID mismatches
- **Error logs**: Database errors, Firebase errors, unexpected exceptions with `exc_info=True` for stack traces

**Debug Prefixes**: Several log messages include `"DEBUG:"` prefix [app/modules/users/user_service.py:123-136]() for development troubleshooting.

**Sources**: [app/modules/users/user_service.py:13](), [app/modules/users/user_router.py:16](), [app/modules/users/user_service.py:117-167]()

## Schema Definitions

The User Service uses Pydantic schemas defined in `user_schema.py` [app/modules/users/user_router.py:7-11]():

| Schema | Purpose | Key Fields |
|--------|---------|------------|
| `CreateUser` | User creation input | `uid`, `email`, `display_name`, `email_verified`, `created_at`, `last_login_at`, `provider_info`, `provider_username` |
| `UserProfileResponse` | Profile picture response | `user_id`, `profile_pic_url` |
| `OnboardingDataRequest` | Onboarding form input | `uid`, `email`, `name`, `source`, `industry`, `jobTitle`, `companyName` |
| `OnboardingDataResponse` | Onboarding save response | `success`, `message` |

These schemas provide request validation, response serialization, and automatic OpenAPI documentation.

**Sources**: [app/modules/users/user_router.py:7-11](), [app/modules/users/user_service.py:10]()

## Usage Examples

### Creating a User

```python
from app.modules.users.user_service import UserService
from app.modules.users.user_schema import CreateUser
from datetime import datetime

user_service = UserService(db_session)

user_data = CreateUser(
    uid="firebase_uid_123",
    email="user@example.com",
    display_name="John Doe",
    email_verified=True,
    created_at=datetime.utcnow(),
    last_login_at=datetime.utcnow(),
    provider_info={"access_token": "oauth_token"},
    provider_username="johndoe"
)

uid, message, error = user_service.create_user(user_data)
if not error:
    print(f"User created: {uid}")
```

### Retrieving User by Email

```python
user = await user_service.get_user_by_email("user@example.com")
if user:
    print(f"Found user: {user.uid}")
```

### Updating Last Login

```python
message, error = user_service.update_last_login(
    uid="firebase_uid_123",
    oauth_token="new_oauth_token"
)
```

**Sources**: [app/modules/users/user_service.py:58-89](), [app/modules/users/user_service.py:138-152](), [app/modules/users/user_service.py:24-56]()