# External Integrations

<cite>
**Referenced Files in This Document**
- [integration_model.py](file://app/modules/integrations/integration_model.py)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py)
- [integrations_router.py](file://app/modules/integrations/integrations_router.py)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py)
- [atlassian_oauth_base.py](file://app/modules/integrations/atlassian_oauth_base.py)
- [jira_oauth.py](file://app/modules/integrations/jira_oauth.py)
- [confluence_oauth.py](file://app/modules/integrations/confluence_oauth.py)
- [linear_oauth.py](file://app/modules/integrations/linear_oauth.py)
- [token_encryption.py](file://app/modules/integrations/token_encryption.py)
- [webhook_handler.py](file://app/modules/event_bus/handlers/webhook_handler.py)
- [github_provider.py](file://app/modules/code_provider/github/github_provider.py)
- [github_service.py](file://app/modules/code_provider/github/github_service.py)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)
10. [Appendices](#appendices)

## Introduction
This document explains Potpie’s external integration system that connects the platform with third-party services such as GitHub, Sentry, Linear, and Atlassian’s Jira and Confluence. It covers the integration layer’s purpose, OAuth flows, token management, API communication patterns, and service-specific tooling. The guide is designed for both beginners (conceptual overviews) and experienced developers (implementation details, schemas, and workflows).

## Project Structure
The integration system is organized around:
- A shared database model for integrations
- A service layer orchestrating OAuth, token lifecycle, and API calls
- Router endpoints for OAuth initiation, callbacks, and webhook handling
- Provider abstractions for GitHub
- Atlassian OAuth base class and product-specific handlers
- Token encryption utilities
- Webhook event processing

```mermaid
graph TB
subgraph "Integrations Layer"
IM["Integration Model<br/>(integration_model.py)"]
IS["Integrations Service<br/>(integrations_service.py)"]
IR["Integrations Router<br/>(integrations_router.py)"]
SC["Schemas<br/>(integrations_schema.py)"]
TE["Token Encryption<br/>(token_encryption.py)"]
WH["Webhook Handler<br/>(webhook_handler.py)"]
end
subgraph "Atlassian Providers"
AO["Atlassian OAuth Base<br/>(atlassian_oauth_base.py)"]
JO["Jira OAuth<br/>(jira_oauth.py)"]
CO["Confluence OAuth<br/>(confluence_oauth.py)"]
end
subgraph "Linear Provider"
LO["Linear OAuth<br/>(linear_oauth.py)"]
end
subgraph "GitHub Providers"
GP["GitHub Provider<br/>(github_provider.py)"]
GS["GitHub Service<br/>(github_service.py)"]
end
IR --> IS
IS --> IM
IS --> TE
IS --> JO
IS --> CO
IS --> LO
JO --> AO
CO --> AO
WH --> IS
GS --> GP
```

**Diagram sources**
- [integration_model.py](file://app/modules/integrations/integration_model.py#L7-L44)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L40-L49)
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L52-L117)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L65-L96)
- [token_encryption.py](file://app/modules/integrations/token_encryption.py#L14-L97)
- [webhook_handler.py](file://app/modules/event_bus/handlers/webhook_handler.py#L17-L29)
- [atlassian_oauth_base.py](file://app/modules/integrations/atlassian_oauth_base.py#L56-L71)
- [jira_oauth.py](file://app/modules/integrations/jira_oauth.py#L12-L31)
- [confluence_oauth.py](file://app/modules/integrations/confluence_oauth.py#L16-L76)
- [linear_oauth.py](file://app/modules/integrations/linear_oauth.py#L51-L64)
- [github_provider.py](file://app/modules/code_provider/github/github_provider.py#L16-L25)
- [github_service.py](file://app/modules/code_provider/github/github_service.py#L35-L60)

**Section sources**
- [integration_model.py](file://app/modules/integrations/integration_model.py#L7-L44)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L40-L49)
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L52-L117)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L65-L96)
- [token_encryption.py](file://app/modules/integrations/token_encryption.py#L14-L97)
- [webhook_handler.py](file://app/modules/event_bus/handlers/webhook_handler.py#L17-L29)
- [atlassian_oauth_base.py](file://app/modules/integrations/atlassian_oauth_base.py#L56-L71)
- [jira_oauth.py](file://app/modules/integrations/jira_oauth.py#L12-L31)
- [confluence_oauth.py](file://app/modules/integrations/confluence_oauth.py#L16-L76)
- [linear_oauth.py](file://app/modules/integrations/linear_oauth.py#L51-L64)
- [github_provider.py](file://app/modules/code_provider/github/github_provider.py#L16-L25)
- [github_service.py](file://app/modules/code_provider/github/github_service.py#L35-L60)

## Core Components
- Integration Model: Defines the persistent structure for integrations, including auth_data, scope_data, and metadata.
- Integrations Service: Central coordinator for OAuth flows, token lifecycle, API calls, and integration persistence.
- Integrations Router: Exposes endpoints for OAuth initiation, callbacks, status checks, revocation, and webhook redirections.
- Schemas: Strongly typed request/response models for integrations and OAuth operations.
- Atlassian OAuth Base: Shared OAuth 2.0 (3LO) implementation for Jira and Confluence.
- Jira OAuth: Adds product-specific API calls and webhook management.
- Confluence OAuth: Extends Atlassian base with product-specific scopes.
- Linear OAuth: Handles Linear OAuth flow and token exchange.
- Token Encryption: Securely stores tokens using symmetric encryption.
- Webhook Handler: Processes inbound webhook events and routes them by integration type.

**Section sources**
- [integration_model.py](file://app/modules/integrations/integration_model.py#L7-L44)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L40-L49)
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L52-L117)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L65-L96)
- [atlassian_oauth_base.py](file://app/modules/integrations/atlassian_oauth_base.py#L56-L71)
- [jira_oauth.py](file://app/modules/integrations/jira_oauth.py#L12-L31)
- [confluence_oauth.py](file://app/modules/integrations/confluence_oauth.py#L16-L76)
- [linear_oauth.py](file://app/modules/integrations/linear_oauth.py#L51-L64)
- [token_encryption.py](file://app/modules/integrations/token_encryption.py#L14-L97)
- [webhook_handler.py](file://app/modules/event_bus/handlers/webhook_handler.py#L17-L29)

## Architecture Overview
The integration layer follows a layered architecture:
- Router exposes endpoints for OAuth and webhook handling.
- Service layer manages OAuth exchanges, token storage, and API calls.
- Database persists integration records with encrypted tokens.
- Providers encapsulate product-specific logic (Atlassian OAuth base, Linear, GitHub).

```mermaid
sequenceDiagram
participant FE as "Frontend"
participant IR as "Integrations Router"
participant IS as "Integrations Service"
participant TP as "Third Party OAuth"
participant DB as "Database"
FE->>IR : "Initiate OAuth"
IR->>TP : "Redirect to authorization URL"
FE->>TP : "User authorizes"
TP-->>IR : "Callback with authorization code"
IR->>IS : "Save integration (exchange code)"
IS->>TP : "Exchange code for tokens"
TP-->>IS : "Access/Refresh tokens"
IS->>DB : "Persist integration with encrypted tokens"
IS-->>IR : "Success response"
IR-->>FE : "Integration saved"
```

**Diagram sources**
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L180-L243)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L595-L788)
- [integration_model.py](file://app/modules/integrations/integration_model.py#L7-L44)
- [token_encryption.py](file://app/modules/integrations/token_encryption.py#L63-L93)

## Detailed Component Analysis

### Integration Model and Persistence
- Stores integration identifiers, type, status, and activity flag.
- Holds JSON fields for auth_data (tokens, scopes), scope_data (org/workspace/project), and metadata.
- Includes system fields for ownership and timestamps.

```mermaid
classDiagram
class Integration {
+string integration_id
+string name
+string integration_type
+string status
+boolean active
+JSONB auth_data
+JSONB scope_data
+JSONB integration_metadata
+string unique_identifier
+string created_by
+TIMESTAMP created_at
+TIMESTAMP updated_at
}
```

**Diagram sources**
- [integration_model.py](file://app/modules/integrations/integration_model.py#L7-L44)

**Section sources**
- [integration_model.py](file://app/modules/integrations/integration_model.py#L7-L44)

### OAuth Flows and Token Management
- Sentry OAuth: Router endpoints for initiation, callback, status, and revocation; service handles token exchange, refresh, and API calls; tokens are encrypted before storage.
- Linear OAuth: Router endpoints for initiation, callback, status, and revocation; service saves integration after exchanging code; tokens cached per user.
- Atlassian OAuth (Jira/Confluence): Shared base class implements authorization URL generation, token exchange, refresh, and accessible resources discovery; product-specific handlers add API calls and Jira webhook management.

```mermaid
sequenceDiagram
participant FE as "Frontend"
participant IR as "Integrations Router"
participant IS as "Integrations Service"
participant TP as "Sentry OAuth"
participant DB as "Database"
FE->>IR : "POST /integrations/sentry/initiate"
IR->>TP : "Generate authorization URL"
TP-->>IR : "Authorization URL"
IR-->>FE : "Redirect URL"
FE->>TP : "Authorize"
TP-->>IR : "Callback with code"
IR->>IS : "Save Sentry integration"
IS->>TP : "Exchange code for tokens"
TP-->>IS : "Tokens"
IS->>DB : "Persist encrypted tokens"
IS-->>IR : "Success"
IR-->>FE : "Saved"
```

**Diagram sources**
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L180-L243)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L595-L788)
- [token_encryption.py](file://app/modules/integrations/token_encryption.py#L63-L93)

**Section sources**
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L180-L243)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L132-L162)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L354-L487)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L595-L788)
- [token_encryption.py](file://app/modules/integrations/token_encryption.py#L63-L93)

### Atlassian OAuth Base and Jira/Confluence Providers
- AtlassianOAuthBase: Provides shared OAuth 2.0 (3LO) infrastructure, including authorization URL construction, token exchange, refresh, and accessible resources retrieval.
- JiraOAuth: Extends base with product-specific scopes and adds webhook creation/deletion APIs.
- ConfluenceOAuth: Extends base with product-specific scopes; notes that Confluence OAuth 2.0 apps cannot register webhooks via API.

```mermaid
classDiagram
class AtlassianOAuthBase {
+Config config
+AtlassianOAuthStore token_store
+string product_name
+string default_scope
+get_authorization_url(redirect_uri, state, scope, prompt) string
+exchange_code_for_tokens(code, redirect_uri) Dict
+refresh_access_token(refresh_token) Dict
+get_accessible_resources(access_token) Dict
+handle_callback(request, user_id) Dict
+get_user_info(user_id) Dict
+revoke_access(user_id) bool
}
class JiraOAuth {
+string default_scope
+create_webhook(cloud_id, access_token, webhook_url, events, jql, name) Dict
+delete_webhook(cloud_id, access_token, webhook_id) bool
}
class ConfluenceOAuth {
+string default_scope
}
JiraOAuth --|> AtlassianOAuthBase
ConfluenceOAuth --|> AtlassianOAuthBase
```

**Diagram sources**
- [atlassian_oauth_base.py](file://app/modules/integrations/atlassian_oauth_base.py#L56-L383)
- [jira_oauth.py](file://app/modules/integrations/jira_oauth.py#L12-L149)
- [confluence_oauth.py](file://app/modules/integrations/confluence_oauth.py#L16-L82)

**Section sources**
- [atlassian_oauth_base.py](file://app/modules/integrations/atlassian_oauth_base.py#L56-L383)
- [jira_oauth.py](file://app/modules/integrations/jira_oauth.py#L12-L149)
- [confluence_oauth.py](file://app/modules/integrations/confluence_oauth.py#L16-L82)

### Linear OAuth Integration
- Router endpoints for initiation, callback, status, and revocation.
- Service saves integration after exchanging authorization code for tokens.
- Tokens cached per user in-memory store.

```mermaid
sequenceDiagram
participant FE as "Frontend"
participant IR as "Integrations Router"
participant LO as "LinearOAuth"
participant IS as "Integrations Service"
participant DB as "Database"
FE->>IR : "GET /integrations/linear/redirect"
IR->>LO : "get_authorization_url()"
LO-->>IR : "Authorization URL"
IR-->>FE : "Redirect"
FE->>LO : "Authorize"
LO-->>IR : "Callback with code"
IR->>IS : "save_linear_integration()"
IS->>LO : "exchange_code_for_tokens()"
LO-->>IS : "Tokens"
IS->>DB : "Persist integration"
IS-->>IR : "Success"
IR-->>FE : "Redirect success"
```

**Diagram sources**
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L385-L542)
- [linear_oauth.py](file://app/modules/integrations/linear_oauth.py#L65-L156)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L595-L788)

**Section sources**
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L385-L542)
- [linear_oauth.py](file://app/modules/integrations/linear_oauth.py#L65-L156)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L595-L788)

### GitHub Integration
- GitHubProvider implements ICodeProvider with support for PAT, OAuth token, and App installation authentication.
- GitHubService coordinates repository access, file content retrieval, branch listing, and project structure traversal; supports both authenticated and public access with fallback strategies.

```mermaid
classDiagram
class GitHubProvider {
+authenticate(credentials, method) Github
+set_unauthenticated_client() Github
+get_supported_auth_methods() List
+get_repository(repo_name) Dict
+get_file_content(repo_name, file_path, ref, start_line, end_line) str
+get_repository_structure(repo_name, path, ref, max_depth) List
+list_branches(repo_name) List
+create_branch(repo_name, branch_name, base_branch) Dict
+compare_branches(repo_name, base_branch, head_branch) Dict
+list_pull_requests(repo_name, state, limit) List
+get_pull_request(repo_name, pr_number, include_diff) Dict
+create_pull_request(repo_name, title, body, head_branch, base_branch, reviewers, labels) Dict
+add_pull_request_comment(repo_name, pr_number, body, commit_id, path, line) Dict
+create_pull_request_review(repo_name, pr_number, body, event, comments) Dict
+list_issues(repo_name, state, limit) List
+get_issue(repo_name, issue_number) Dict
+create_issue(repo_name, title, body, labels) Dict
+create_or_update_file(repo_name, file_path, content, commit_message, branch, author_name, author_email) Dict
+list_user_repositories(user_id) List
+get_user_organizations() List
+get_provider_name() string
+get_api_base_url() string
+get_rate_limit_info() Dict
}
```

**Diagram sources**
- [github_provider.py](file://app/modules/code_provider/github/github_provider.py#L16-L733)

**Section sources**
- [github_provider.py](file://app/modules/code_provider/github/github_provider.py#L16-L733)
- [github_service.py](file://app/modules/code_provider/github/github_service.py#L35-L60)
- [github_service.py](file://app/modules/code_provider/github/github_service.py#L690-L704)

### Webhook Handling
- WebhookEventHandler processes inbound webhook events, validates integration presence, and routes processing by integration type.
- Integrations Router includes endpoints to log and route webhook events for Sentry, Linear, and Jira.

```mermaid
flowchart TD
Start(["Incoming Webhook"]) --> Validate["Validate integration exists and active"]
Validate --> Route{"Integration type?"}
Route --> |Linear| ProcessLinear["Extract action/data<br/>Map to issue/project"]
Route --> |Sentry| ProcessSentry["Extract action/data<br/>Map to issue/project"]
Route --> |Other| ProcessGeneric["Store raw payload"]
ProcessLinear --> Store["Persist/log event"]
ProcessSentry --> Store
ProcessGeneric --> Store
Store --> End(["Return result"])
```

**Diagram sources**
- [webhook_handler.py](file://app/modules/event_bus/handlers/webhook_handler.py#L30-L177)
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L385-L542)

**Section sources**
- [webhook_handler.py](file://app/modules/event_bus/handlers/webhook_handler.py#L30-L177)
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L385-L542)

## Dependency Analysis
- Router depends on service layer and provider instances for OAuth.
- Service depends on provider implementations, database model, and token encryption.
- Atlassian providers depend on shared base class and product-specific configuration.
- GitHub service depends on provider factory and GitHub provider.

```mermaid
graph TB
IR["integrations_router.py"] --> IS["integrations_service.py"]
IS --> IM["integration_model.py"]
IS --> TE["token_encryption.py"]
IS --> JO["jira_oauth.py"]
IS --> CO["confluence_oauth.py"]
IS --> LO["linear_oauth.py"]
JO --> AO["atlassian_oauth_base.py"]
CO --> AO
GS["github_service.py"] --> GP["github_provider.py"]
```

**Diagram sources**
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L52-L117)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L40-L49)
- [integration_model.py](file://app/modules/integrations/integration_model.py#L7-L44)
- [token_encryption.py](file://app/modules/integrations/token_encryption.py#L14-L97)
- [jira_oauth.py](file://app/modules/integrations/jira_oauth.py#L12-L31)
- [confluence_oauth.py](file://app/modules/integrations/confluence_oauth.py#L16-L76)
- [linear_oauth.py](file://app/modules/integrations/linear_oauth.py#L51-L64)
- [atlassian_oauth_base.py](file://app/modules/integrations/atlassian_oauth_base.py#L56-L71)
- [github_service.py](file://app/modules/code_provider/github/github_service.py#L35-L60)
- [github_provider.py](file://app/modules/code_provider/github/github_provider.py#L16-L25)

**Section sources**
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L52-L117)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L40-L49)
- [integration_model.py](file://app/modules/integrations/integration_model.py#L7-L44)
- [token_encryption.py](file://app/modules/integrations/token_encryption.py#L14-L97)
- [jira_oauth.py](file://app/modules/integrations/jira_oauth.py#L12-L31)
- [confluence_oauth.py](file://app/modules/integrations/confluence_oauth.py#L16-L76)
- [linear_oauth.py](file://app/modules/integrations/linear_oauth.py#L51-L64)
- [atlassian_oauth_base.py](file://app/modules/integrations/atlassian_oauth_base.py#L56-L71)
- [github_service.py](file://app/modules/code_provider/github/github_service.py#L35-L60)
- [github_provider.py](file://app/modules/code_provider/github/github_provider.py#L16-L25)

## Performance Considerations
- Token encryption/decryption adds CPU overhead; cache tokens per user in memory for short-lived operations.
- Use asynchronous HTTP clients for OAuth token exchanges and API calls to minimize latency.
- Paginate and batch GitHub API requests; leverage Redis caching for repeated project structure queries.
- Avoid storing authorization codes after exchange; clear sensitive fields post-processing.

## Troubleshooting Guide
Common issues and resolutions:
- OAuth initiation failures: Verify OAuth credentials and redirect URI configuration; ensure state signing secret is set.
- Token exchange failures: Check client credentials, redirect URI match, and code freshness; inspect sanitized error responses.
- Token refresh failures: Confirm refresh token availability and environment configuration; review error logs for structured error fields.
- Webhook processing errors: Validate integration existence and active status; inspect event payload and integration type routing.
- GitHub access errors: Ensure fallback to PAT token list or system tokens; confirm App installation access.

**Section sources**
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L119-L178)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L213-L254)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L298-L302)
- [webhook_handler.py](file://app/modules/event_bus/handlers/webhook_handler.py#L50-L86)
- [github_service.py](file://app/modules/code_provider/github/github_service.py#L340-L363)

## Conclusion
Potpie’s integration layer provides a robust, extensible framework for connecting with GitHub, Sentry, Linear, and Atlassian’s Jira and Confluence. It emphasizes secure token handling, standardized OAuth flows, and flexible webhook processing. The modular design enables straightforward addition of new integrations while maintaining consistent patterns across providers.

## Appendices

### Public Interfaces and Parameters
- Integration Model Fields:
  - integration_id, name, integration_type, status, active
  - auth_data: access_token, refresh_token, token_type, expires_at, scope, code
  - scope_data: org_slug, installation_id, workspace_id, project_id
  - integration_metadata: instance_name, created_via, version, description, tags
  - unique_identifier, created_by, created_at, updated_at

- Integration Save Requests:
  - SentrySaveRequest: code, redirect_uri, instance_name, integration_type, timestamp
  - LinearSaveRequest: code, redirect_uri, instance_name, integration_type, timestamp
  - JiraSaveRequest: code, redirect_uri, instance_name, user_id, integration_type, timestamp
  - ConfluenceSaveRequest: code, redirect_uri, instance_name, user_id, integration_type, timestamp

- OAuth Initiation:
  - OAuthInitiateRequest: redirect_uri, state

- OAuth Status Responses:
  - SentryIntegrationStatus: user_id, is_connected, connected_at, scope, expires_at
  - LinearIntegrationStatus: user_id, is_connected, connected_at, scope, expires_at
  - JiraIntegrationStatus: user_id, is_connected, connected_at, scope, expires_at
  - ConfluenceIntegrationStatus: user_id, is_connected, connected_at, scope, expires_at

- Webhook Logging:
  - log_linear_webhook(webhook_data): returns status, message, logged_at, webhook_data
  - log_jira_webhook(webhook_data): returns status, message, logged_at, webhook_data

**Section sources**
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L65-L96)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L204-L233)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L254-L283)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L296-L321)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L334-L361)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L144-L151)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L178-L186)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L236-L244)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L286-L294)
- [integrations_schema.py](file://app/modules/integrations/integrations_schema.py#L324-L332)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L1323-L1333)
- [integrations_service.py](file://app/modules/integrations/integrations_service.py#L1305-L1321)

### OAuth Configuration Examples
- Sentry:
  - Environment variables: SENTRY_CLIENT_ID, SENTRY_CLIENT_SECRET, SENTRY_REDIRECT_URI
  - Router endpoints: POST /integrations/sentry/initiate, GET /integrations/sentry/callback, GET /integrations/sentry/status/{user_id}, DELETE /integrations/sentry/revoke/{user_id}

- Linear:
  - Environment variables: LINEAR_CLIENT_ID, LINEAR_CLIENT_SECRET
  - Router endpoints: GET /integrations/linear/redirect, GET /integrations/linear/callback, GET /integrations/linear/status/{user_id}, DELETE /integrations/linear/revoke/{user_id}

- Atlassian (Jira/Confluence):
  - Environment variables: JIRA_CLIENT_ID, JIRA_CLIENT_SECRET, CONFLUENCE_CLIENT_ID, CONFLUENCE_CLIENT_SECRET
  - Router endpoints: POST /integrations/jira/initiate, GET /integrations/jira/callback, GET /integrations/jira/status/{user_id}
  - Jira-specific: create/delete webhooks via JiraOAuth methods

**Section sources**
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L180-L243)
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L222-L243)
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L245-L294)
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L385-L542)
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L545-L594)
- [integrations_router.py](file://app/modules/integrations/integrations_router.py#L617-L784)
- [jira_oauth.py](file://app/modules/integrations/jira_oauth.py#L32-L149)
- [confluence_oauth.py](file://app/modules/integrations/confluence_oauth.py#L16-L82)