7.6-Development Mode Authentication

# Page: Development Mode Authentication

# Development Mode Authentication

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.pre-commit-config.yaml](.pre-commit-config.yaml)
- [.python-version](.python-version)
- [app/modules/auth/auth_service.py](app/modules/auth/auth_service.py)
- [app/modules/auth/tests/auth_service_test.py](app/modules/auth/tests/auth_service_test.py)
- [pyproject.toml](pyproject.toml)
- [uv.lock](uv.lock)

</details>



## Purpose and Scope

This document describes the development mode authentication mechanism that allows developers to bypass Firebase authentication during local development. This feature enables rapid development and testing without requiring valid Firebase credentials or internet connectivity.

For production authentication flows, see [Multi-Provider Authentication](#7.1). For general development mode configuration, see [Development Mode](#11.1). For environment variable setup, see [Environment Configuration](#8.3).

---

## Overview

Development mode authentication is a mock authentication system that bypasses Firebase token verification when the application is running in development mode. When enabled, it automatically authenticates requests with a pre-configured default user instead of requiring valid Firebase ID tokens.

**Key characteristics:**
- Bypasses Firebase `auth.verify_id_token()` calls
- Returns a hardcoded user identity
- Only activates when specific environment variables are set
- Disabled automatically in production environments
- Requires no Bearer token when enabled

---

## Configuration

### Environment Variables

Development mode authentication requires two environment variables to be configured:

| Variable | Value | Purpose |
|----------|-------|---------|
| `isDevelopmentMode` | `"enabled"` | Activates development mode authentication |
| `defaultUsername` | String (e.g., `"dev_user"`) | User ID returned for all authenticated requests |

**Example `.env` configuration:**

```env
isDevelopmentMode=enabled
defaultUsername=test-user-123
```

**Sources:** [app/modules/auth/auth_service.py:60-66](), [app/modules/auth/tests/auth_service_test.py:244-246]()

---

## Authentication Flow Comparison

### Development Mode vs Production Mode

```mermaid
graph TB
    subgraph "Request Processing"
        REQ["HTTP Request"]
        CRED_CHECK{"Credential<br/>Provided?"}
        MODE_CHECK{"isDevelopmentMode<br/>== 'enabled'?"}
    end
    
    subgraph "Development Mode Path"
        DEV_USER["Return Mock User:<br/>{user_id: defaultUsername,<br/>email: defaultuser@potpie.ai}"]
        SET_STATE_DEV["request.state.user =<br/>{user_id: defaultUsername}"]
    end
    
    subgraph "Production Mode Path"
        NO_CRED_ERROR["HTTPException<br/>401 Unauthorized<br/>Bearer authentication is needed"]
        VERIFY["auth.verify_id_token()<br/>Firebase Verification"]
        VERIFY_ERROR{"Verification<br/>Success?"}
        DECODE_SUCCESS["Normalize token:<br/>uid → user_id"]
        SET_STATE_PROD["request.state.user =<br/>decoded_token"]
        RETURN_TOKEN["Return decoded_token"]
        FIREBASE_ERROR["HTTPException<br/>401 Unauthorized<br/>Invalid authentication from Firebase"]
    end
    
    REQ --> MODE_CHECK
    MODE_CHECK -->|"Yes"| CRED_CHECK
    MODE_CHECK -->|"No"| CRED_CHECK
    
    CRED_CHECK -->|"None + Dev Mode"| DEV_USER
    CRED_CHECK -->|"None + Prod Mode"| NO_CRED_ERROR
    CRED_CHECK -->|"Present"| VERIFY
    
    DEV_USER --> SET_STATE_DEV
    SET_STATE_DEV --> RETURN_TOKEN
    
    VERIFY --> VERIFY_ERROR
    VERIFY_ERROR -->|"No"| FIREBASE_ERROR
    VERIFY_ERROR -->|"Yes"| DECODE_SUCCESS
    DECODE_SUCCESS --> SET_STATE_PROD
    SET_STATE_PROD --> RETURN_TOKEN
```

**Sources:** [app/modules/auth/auth_service.py:48-104]()

---

## Implementation Details

### AuthService.check_auth Method

The `check_auth` static method in `AuthService` implements the development mode authentication logic. This method is used as a FastAPI dependency via `Depends()` throughout the application.

```mermaid
graph LR
    subgraph "check_auth Method Signature"
        METHOD["AuthService.check_auth()"]
        PARAMS["Parameters:<br/>- request: Request<br/>- res: Response<br/>- credential: HTTPAuthorizationCredentials"]
    end
    
    subgraph "Development Mode Logic"
        ENV_CHECK["os.getenv('isDevelopmentMode')"]
        DEFAULT_USER["os.getenv('defaultUsername')"]
        MOCK_RETURN["Return:<br/>{user_id: defaultUsername,<br/>email: 'defaultuser@potpie.ai'}"]
    end
    
    subgraph "State Management"
        STATE["request.state.user"]
        STATE_VALUE["Set to {user_id: defaultUsername}"]
    end
    
    METHOD --> PARAMS
    PARAMS --> ENV_CHECK
    ENV_CHECK --> DEFAULT_USER
    DEFAULT_USER --> STATE_VALUE
    STATE_VALUE --> STATE
    STATE --> MOCK_RETURN
```

**Code location:** [app/modules/auth/auth_service.py:48-66]()

### Authentication Response Structure

In development mode, the `check_auth` method returns a dictionary with the following structure:

| Field | Value | Type |
|-------|-------|------|
| `user_id` | Value of `defaultUsername` environment variable | `str` |
| `email` | Hardcoded: `"defaultuser@potpie.ai"` | `str` |

**Contrast with production mode:**

In production, Firebase token verification returns additional fields from the decoded JWT token, including:
- `uid` (normalized to `user_id` for consistency)
- `email` (actual user email from Firebase)
- Additional Firebase claims (aud, iat, exp, etc.)

**Sources:** [app/modules/auth/auth_service.py:61-66](), [app/modules/auth/auth_service.py:82-90]()

---

## Request State Population

Both development and production modes populate `request.state.user` to maintain consistency across the application. This allows downstream code to access user information identically regardless of authentication mode.

```mermaid
graph TB
    subgraph "FastAPI Request Object"
        REQUEST["request: Request"]
        STATE["request.state"]
        USER_ATTR["request.state.user"]
    end
    
    subgraph "Development Mode"
        DEV_DICT["{user_id: defaultUsername}"]
    end
    
    subgraph "Production Mode"
        PROD_DICT["decoded_token<br/>(full Firebase token)"]
    end
    
    subgraph "Downstream Usage"
        ROUTER["API Router Endpoint"]
        ACCESS["user_info = request.state.user"]
        USER_ID["user_id = user_info['user_id']"]
    end
    
    REQUEST --> STATE
    STATE --> USER_ATTR
    
    DEV_DICT -.->|"isDevelopmentMode=enabled"| USER_ATTR
    PROD_DICT -.->|"production"| USER_ATTR
    
    USER_ATTR --> ROUTER
    ROUTER --> ACCESS
    ACCESS --> USER_ID
```

**Sources:** [app/modules/auth/auth_service.py:61](), [app/modules/auth/auth_service.py:95]()

---

## Testing with Development Mode

### Test Suite Structure

The test suite in [app/modules/auth/tests/auth_service_test.py]() includes comprehensive coverage of development mode authentication:

```mermaid
graph TB
    subgraph "Test Class: TestAuthCheck"
        TEST_CLASS["TestAuthCheck"]
    end
    
    subgraph "Test Cases"
        T1["test_check_auth_valid_token<br/>Tests production mode with valid Firebase token"]
        T2["test_check_auth_invalid_token<br/>Tests production mode with invalid token"]
        T3["test_check_auth_missing_token<br/>Tests production mode without credential"]
        T4["test_check_auth_development_mode<br/>Tests dev mode returns mock user"]
        T5["test_check_auth_expired_token<br/>Tests production mode with expired token"]
        T6["test_check_auth_malformed_token<br/>Tests production mode with malformed token"]
    end
    
    subgraph "Mock Objects"
        MOCK_REQ["mock_request"]
        MOCK_RES["mock_response"]
        MOCK_CRED["mock_credential"]
        PATCH_ENV["patch.dict(os.environ)"]
        PATCH_FIREBASE["patch('firebase_admin.auth.verify_id_token')"]
    end
    
    TEST_CLASS --> T1
    TEST_CLASS --> T2
    TEST_CLASS --> T3
    TEST_CLASS --> T4
    TEST_CLASS --> T5
    TEST_CLASS --> T6
    
    T4 --> PATCH_ENV
    T4 --> MOCK_REQ
    T4 --> MOCK_RES
    
    T1 --> PATCH_FIREBASE
    T1 --> MOCK_CRED
```

### Development Mode Test Example

The test at [app/modules/auth/tests/auth_service_test.py:236-252]() demonstrates the expected behavior:

**Test steps:**
1. Patch environment variables: `isDevelopmentMode="enabled"`, `defaultUsername="dev_user"`
2. Call `check_auth()` with `credential=None`
3. Assert returned user_id matches `defaultUsername`
4. Assert email is `"defaultuser@potpie.ai"`
5. Assert `request.state.user` is populated correctly

**Sources:** [app/modules/auth/tests/auth_service_test.py:236-252]()

---

## Security Considerations

### Production Safety Mechanisms

Development mode authentication includes several safety mechanisms to prevent accidental use in production:

```mermaid
graph TB
    subgraph "Safety Checks"
        CHECK1{"isDevelopmentMode<br/>== 'enabled'?"}
        CHECK2{"credential<br/>is None?"}
        BOTH{"Both conditions<br/>true?"}
    end
    
    subgraph "Outcomes"
        MOCK["Use Mock Auth"]
        NORMAL["Use Firebase Auth"]
    end
    
    CHECK1 -->|"Yes"| CHECK2
    CHECK1 -->|"No"| NORMAL
    CHECK2 -->|"Yes"| BOTH
    CHECK2 -->|"No"| NORMAL
    BOTH -->|"Yes"| MOCK
    BOTH -->|"No"| NORMAL
```

**Critical security points:**

1. **Dual-condition requirement**: Development mode only activates when BOTH `isDevelopmentMode="enabled"` AND no credential is provided
2. **If a Bearer token is sent**: Even with development mode enabled, the presence of a credential triggers normal Firebase verification
3. **Environment-based**: The mode is controlled by environment variables, which should never be set to "enabled" in production deployments
4. **No backdoor access**: There is no secret token or bypass mechanism; production environments must have `isDevelopmentMode` unset or set to any value other than "enabled"

**Sources:** [app/modules/auth/auth_service.py:60-76]()

### Recommended Deployment Practices

| Environment | `isDevelopmentMode` | `defaultUsername` | Notes |
|-------------|---------------------|-------------------|-------|
| Local Development | `"enabled"` | Any string (e.g., `"dev_user"`) | Enables rapid development |
| CI/CD Testing | `"enabled"` | `"test_user"` | Allows automated tests without Firebase |
| Staging | Unset or `"disabled"` | Unset | Should use real Firebase auth |
| Production | **Must be unset** | **Must be unset** | Never enable in production |

**Sources:** [app/modules/auth/auth_service.py:60]()

---

## Logging and Debugging

The `check_auth` method includes extensive debug logging to help developers understand which authentication path is being used:

**Log statements in development mode:**
- `"DEBUG: AuthService.check_auth called"`
- `"DEBUG: Development mode: <value>"`
- `"DEBUG: Credential provided: <boolean>"`
- `"DEBUG: Development mode enabled. Using Mock Authentication."`

**Log statements in production mode:**
- `"DEBUG: Verifying Firebase token: <token_prefix>..."`
- `"DEBUG: Successfully verified token for user: <user_id>"`
- `"DEBUG: Token email: <email>"`
- `"DEBUG: Firebase token verification failed: <error>"`

These logs appear when the application is run with appropriate logging configuration.

**Sources:** [app/modules/auth/auth_service.py:55-62](), [app/modules/auth/auth_service.py:78-97]()

---

## Integration with FastAPI Dependency Injection

### Usage Pattern Across Routers

The `auth_handler.check_auth` method is used as a FastAPI dependency throughout the application's router endpoints:

```mermaid
graph TB
    subgraph "auth_service.py"
        AUTH_SERVICE["AuthService class"]
        CHECK_AUTH["check_auth() static method"]
        AUTH_HANDLER["auth_handler = AuthService()"]
    end
    
    subgraph "API Routers"
        ROUTE1["@router.post('/conversations/{id}/message')"]
        ROUTE2["@router.get('/projects')"]
        ROUTE3["@router.post('/custom-agents')"]
        DEPENDS["Depends(auth_handler.check_auth)"]
    end
    
    subgraph "Request Processing"
        FASTAPI["FastAPI Framework"]
        INJECT["Dependency Injection"]
        USER["user = request.state.user"]
    end
    
    AUTH_SERVICE --> CHECK_AUTH
    CHECK_AUTH --> AUTH_HANDLER
    
    ROUTE1 --> DEPENDS
    ROUTE2 --> DEPENDS
    ROUTE3 --> DEPENDS
    
    DEPENDS --> INJECT
    FASTAPI --> INJECT
    INJECT --> USER
```

**Sources:** [app/modules/auth/auth_service.py:107]()

### Dependency Declaration

Endpoints typically declare the authentication dependency like this:

```python
async def endpoint(
    user=Depends(auth_handler.check_auth),
    # other parameters...
):
    user_id = user["user_id"]
    # endpoint logic...
```

In development mode, `user` will contain the mock user dictionary. In production, it will contain the decoded Firebase token.

**Sources:** [app/modules/auth/auth_service.py:107]()

---

## Comparison Table: Development vs Production Authentication

| Aspect | Development Mode | Production Mode |
|--------|------------------|-----------------|
| **Activation** | `isDevelopmentMode="enabled"` | `isDevelopmentMode` unset or any value != "enabled" |
| **Token Required** | No (unless explicitly provided) | Yes (Bearer token mandatory) |
| **Verification Method** | No verification | Firebase `auth.verify_id_token()` |
| **User ID Source** | `defaultUsername` environment variable | Firebase JWT `uid` field |
| **Email Source** | Hardcoded `"defaultuser@potpie.ai"` | Firebase JWT `email` field |
| **Request Time** | Near-instant (no network call) | Network latency to Firebase API |
| **Error Handling** | Always succeeds (when conditions met) | Can fail with 401 if token invalid |
| **User Claims** | Minimal (user_id, email only) | Full Firebase token claims |
| **State Population** | `request.state.user = {user_id: ...}` | `request.state.user = decoded_token` |
| **Security Risk** | High if enabled in production | Standard Firebase security model |

**Sources:** [app/modules/auth/auth_service.py:60-104]()

---

## Related Configuration Files

### Environment Template

The repository includes environment variable templates that developers should use to configure development mode. While not directly shown in the provided files, the standard practice is to have a `.env.template` or `.env.example` file.

### Python Version

The application requires Python 3.10 or higher, as specified in:
- [.python-version:1]() - specifies `3.13`
- [pyproject.toml:6]() - specifies `requires-python = ">=3.10"`

**Sources:** [.python-version:1](), [pyproject.toml:6]()

---

## Summary

Development mode authentication provides a streamlined authentication bypass for local development by:

1. Checking the `isDevelopmentMode` environment variable
2. Returning a mock user when enabled and no credential is provided
3. Maintaining the same `request.state.user` interface as production
4. Including dual-condition safety to prevent accidental production use
5. Supporting the same dependency injection pattern across all endpoints

This feature enables developers to work on the application without requiring Firebase connectivity or credentials, while maintaining a consistent authentication interface throughout the codebase.

**Sources:** [app/modules/auth/auth_service.py:48-104](), [app/modules/auth/tests/auth_service_test.py:236-252]()