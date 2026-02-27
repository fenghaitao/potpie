3.3-Multimodal Support

# Page: Multimodal Support

# Multimodal Support

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [app/modules/conversations/conversation/conversation_controller.py](app/modules/conversations/conversation/conversation_controller.py)
- [app/modules/conversations/conversation/conversation_schema.py](app/modules/conversations/conversation/conversation_schema.py)
- [app/modules/conversations/conversation/conversation_service.py](app/modules/conversations/conversation/conversation_service.py)
- [app/modules/conversations/conversations_router.py](app/modules/conversations/conversations_router.py)

</details>



## Purpose and Scope

This document describes the multimodal support system in Potpie's conversation platform, focusing on image attachment handling, vision model integration, and multimodal context preparation. The system enables users to include images in their messages, which are then processed and provided to AI agents for visual analysis alongside text queries.

For information about general conversation management and message handling, see [Conversation Service and Lifecycle](#3.1). For details on agent execution with multimodal inputs, see [Agent Execution Pipeline](#2.5).

## System Overview

The multimodal support system handles three primary workflows:

1. **Image Upload and Storage**: Images uploaded by users are stored via `MediaService` and linked to messages through attachment records
2. **Multimodal Context Preparation**: Attachments are retrieved and converted to base64-encoded images for AI processing
3. **Vision Model Integration**: Prepared images are passed to agents through `ChatContext` for multimodal inference

```mermaid
graph TB
    subgraph "Upload Phase"
        USER["User Uploads Image"]
        ROUTER["conversations_router.py<br/>post_message endpoint"]
        MEDIA["MediaService<br/>upload_image"]
        STORAGE["Object Storage<br/>GCS/S3/Azure"]
        DB[(PostgreSQL<br/>attachments table)]
    end
    
    subgraph "Retrieval Phase"
        MSG_STORE["MessageStore<br/>get message with attachments"]
        PREP_ATT["ConversationService<br/>_prepare_attachments_as_images"]
        PREP_CTX["ConversationService<br/>_prepare_conversation_context_images"]
        BASE64["Base64 Conversion<br/>MediaService.get_image_as_base64"]
    end
    
    subgraph "Agent Execution Phase"
        CHAT_CTX["ChatContext<br/>image_attachments + context_images"]
        AGENT_SVC["AgentService<br/>execute_stream"]
        PROVIDER["ProviderService<br/>Vision Model API"]
    end
    
    USER --> ROUTER
    ROUTER --> MEDIA
    MEDIA --> STORAGE
    MEDIA --> DB
    
    DB --> MSG_STORE
    MSG_STORE --> PREP_ATT
    MSG_STORE --> PREP_CTX
    PREP_ATT --> BASE64
    PREP_CTX --> BASE64
    
    BASE64 --> CHAT_CTX
    CHAT_CTX --> AGENT_SVC
    AGENT_SVC --> PROVIDER
```

**Sources**: [app/modules/conversations/conversation/conversation_service.py:1-1323](), [app/modules/conversations/conversations_router.py:160-286]()

## Image Attachment Upload

### Upload Endpoint

The `/conversations/{conversation_id}/message/` endpoint accepts image uploads as multipart form data. Images are processed before the message is stored, and attachment IDs are associated with the message record.

| Parameter | Type | Description |
|-----------|------|-------------|
| `content` | `str` (Form) | Message text content |
| `node_ids` | `Optional[str]` (Form) | JSON array of node IDs for context |
| `images` | `Optional[List[UploadFile]]` (File) | Image files to attach |
| `stream` | `bool` (Query) | Whether to stream the response |

```mermaid
sequenceDiagram
    participant Client
    participant Router as conversations_router.py
    participant MediaSvc as MediaService
    participant Storage as Object Storage
    participant DB as PostgreSQL
    participant ConvSvc as ConversationService
    
    Client->>Router: POST /conversations/{id}/message<br/>FormData: content, images[]
    
    Router->>Router: Validate content not empty
    
    loop For each image
        Router->>Router: Read file content
        Router->>MediaSvc: upload_image(file_content, filename, mime_type)
        MediaSvc->>Storage: Store image object
        MediaSvc->>DB: INSERT INTO attachments
        MediaSvc-->>Router: Return attachment_id
        Router->>Router: Collect attachment_ids[]
    end
    
    Router->>Router: Create MessageRequest<br/>with attachment_ids
    Router->>ConvSvc: store_message(message, attachment_ids)
    ConvSvc->>DB: Link attachments to message_id
    ConvSvc-->>Router: Stream AI response
    Router-->>Client: Server-Sent Events
```

**Sources**: [app/modules/conversations/conversations_router.py:160-286]()

### Error Handling and Cleanup

If image upload fails for any attachment, all previously uploaded attachments for that request are cleaned up to prevent orphaned records.

```mermaid
graph LR
    START["Upload Image 1"]
    UPLOAD1["Success: attachment_id_1"]
    UPLOAD2["Upload Image 2"]
    FAIL["Failure Exception"]
    CLEANUP["Delete attachment_id_1"]
    ERROR["Return HTTP 400"]
    
    START --> UPLOAD1
    UPLOAD1 --> UPLOAD2
    UPLOAD2 --> FAIL
    FAIL --> CLEANUP
    CLEANUP --> ERROR
```

**Sources**: [app/modules/conversations/conversations_router.py:214-235]()

## Attachment Storage and Retrieval

### Linking Attachments to Messages

After a message is stored, attachments are linked via the `MediaService.update_message_attachments` method. This creates a many-to-many relationship between messages and attachments.

**Sources**: [app/modules/conversations/conversation/conversation_service.py:569-584]()

### Attachment Data Structure

The `MediaService` returns attachment metadata including:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique attachment identifier |
| `attachment_type` | `AttachmentType.IMAGE` | Type of attachment |
| `mime_type` | `str` | Image MIME type (e.g., `image/png`) |
| `file_name` | `str` | Original filename |
| `file_size` | `int` | Size in bytes |
| `message_id` | `str` | Associated message ID |

**Sources**: [app/modules/conversations/conversation/conversation_service.py:1058-1074]()

## Multimodal Context Preparation

The conversation service prepares multimodal context through three primary methods that convert stored attachments into base64-encoded images suitable for vision model APIs.

### Current Message Images

The `_prepare_attachments_as_images` method converts a list of attachment IDs directly to base64 format:

```mermaid
graph TB
    INPUT["attachment_ids: List[str]"]
    LOOP["For each attachment_id"]
    GET_ATT["MediaService.get_attachment<br/>Retrieve attachment metadata"]
    CHECK["Check attachment_type == IMAGE"]
    GET_B64["MediaService.get_image_as_base64<br/>Download and encode"]
    BUILD["Build image dict:<br/>{attachment_id: {base64, mime_type, file_name, file_size}}"]
    RETURN["Return images: Dict[str, Dict]"]
    SKIP["Skip non-image attachments"]
    
    INPUT --> LOOP
    LOOP --> GET_ATT
    GET_ATT --> CHECK
    CHECK -->|Yes| GET_B64
    CHECK -->|No| SKIP
    GET_B64 --> BUILD
    BUILD --> LOOP
    LOOP --> RETURN
    SKIP --> LOOP
```

**Implementation Details**:
- Only processes attachments with `attachment_type.value.upper() == "IMAGE"`
- Logs detailed information about processed vs. skipped attachments
- Returns `None` if no valid images are found
- Continues processing remaining attachments if one fails

**Sources**: [app/modules/conversations/conversation/conversation_service.py:1046-1096]()

### Conversation Context Images

The `_prepare_conversation_context_images` method retrieves recent images from conversation history to provide additional visual context:

```mermaid
graph TB
    INPUT["conversation_id: str<br/>limit: int = 3"]
    GET_MSGS["MessageStore.get_recent_messages_with_images<br/>Query recent human messages"]
    COLLECT["Collect message_ids with attachments"]
    LOOP["For each message_id"]
    GET_IMGS["MediaService.get_message_images_as_base64<br/>Retrieve all image attachments"]
    MERGE["Merge into images dict"]
    LIMIT_CHECK{"Reached<br/>limit?"}
    RETURN["Return context_images: Dict[str, Dict]"]
    
    INPUT --> GET_MSGS
    GET_MSGS --> COLLECT
    COLLECT --> LOOP
    LOOP --> GET_IMGS
    GET_IMGS --> MERGE
    MERGE --> LIMIT_CHECK
    LIMIT_CHECK -->|No| LOOP
    LIMIT_CHECK -->|Yes| RETURN
```

**Configuration**:
- Default limit: 3 recent messages with images
- Excludes the current message (handled separately)
- Provides chronological context for multi-turn visual conversations

**Sources**: [app/modules/conversations/conversation/conversation_service.py:1126-1148]()

### Context Assembly

During AI response generation, both current and context images are prepared and combined:

| Context Type | Method | Purpose |
|-------------|---------|---------|
| Current Message | `_prepare_attachments_as_images(attachment_ids)` | Images explicitly uploaded with this message |
| Historical Context | `_prepare_conversation_context_images(conversation_id)` | Recent images from conversation history |

**Sources**: [app/modules/conversations/conversation/conversation_service.py:927-947]()

## Vision Model Integration

### ChatContext Structure

Multimodal data is passed to agents through the `ChatContext` object, which includes:

```python
ChatContext(
    project_id=str,
    project_name=str,
    curr_agent_id=str,
    history=List[str],          # Recent conversation history
    node_ids=List[str],         # Code graph nodes for context
    query=str,                  # User's text query
    image_attachments=Dict,     # Current message images
    context_images=Dict,        # Historical conversation images
    conversation_id=str
)
```

**Sources**: [app/modules/conversations/conversation/conversation_service.py:983-994]()

### Agent Execution Flow

```mermaid
sequenceDiagram
    participant ConvSvc as ConversationService
    participant MediaSvc as MediaService
    participant AgentSvc as AgentService
    participant Provider as ProviderService
    participant LLM as Vision Model API
    
    ConvSvc->>MediaSvc: _prepare_attachments_as_images(attachment_ids)
    MediaSvc-->>ConvSvc: image_attachments: Dict
    
    ConvSvc->>MediaSvc: _prepare_conversation_context_images(conversation_id)
    MediaSvc-->>ConvSvc: context_images: Dict
    
    ConvSvc->>ConvSvc: Build ChatContext with images
    
    ConvSvc->>AgentSvc: execute_stream(ChatContext)
    AgentSvc->>AgentSvc: Route to appropriate agent
    AgentSvc->>Provider: call_llm_with_structured_output<br/>with vision content
    Provider->>LLM: API request with base64 images
    LLM-->>Provider: Streaming response
    Provider-->>AgentSvc: Response chunks
    AgentSvc-->>ConvSvc: Stream chunks
```

**Conditional Processing**:
- If `image_attachments` or `context_images` exist, agents use vision-enabled models
- The `ProviderService` automatically selects compatible vision models (e.g., GPT-4 Vision, Claude 3)
- Non-vision agents ignore image fields and process only text

**Sources**: [app/modules/conversations/conversation/conversation_service.py:891-1028]()

## Regeneration with Multimodal Context

When regenerating the last AI response, the system retrieves attachments from the previous human message to maintain multimodal context.

### Regeneration Flow

```mermaid
graph TB
    REQ["Regeneration Request"]
    GET_MSG["Get last human message"]
    CHECK["Check has_attachments flag"]
    GET_ATT["MediaService.get_message_attachments"]
    FILTER["Filter for IMAGE attachments only"]
    COLLECT["Collect attachment_ids"]
    PREP["Prepare multimodal context"]
    EXEC["Execute agent with images"]
    
    REQ --> GET_MSG
    GET_MSG --> CHECK
    CHECK -->|True| GET_ATT
    CHECK -->|False| EXEC
    GET_ATT --> FILTER
    FILTER --> COLLECT
    COLLECT --> PREP
    PREP --> EXEC
```

**Implementation Notes**:
- Uses `AttachmentType.IMAGE` filter to exclude non-image attachments
- Logs the number of image attachments found
- Continues regeneration even if attachment retrieval fails (logs warning)
- Maintains consistency with original message's visual context

**Sources**: [app/modules/conversations/conversation/conversation_service.py:703-732](), [app/modules/conversations/conversations_router.py:343-366]()

### Background Regeneration

For background regeneration tasks (via Celery), attachment IDs are passed as task parameters:

```python
execute_regenerate_background.delay(
    conversation_id=conversation_id,
    run_id=run_id,
    user_id=user_id,
    node_ids=node_ids,
    attachment_ids=attachment_ids  # Extracted from last human message
)
```

**Sources**: [app/modules/conversations/conversations_router.py:387-393]()

## Data Flow Summary

The complete multimodal data flow from upload to vision model inference:

| Stage | Component | Input | Output |
|-------|-----------|-------|--------|
| 1. Upload | `conversations_router.post_message` | `List[UploadFile]` | `List[attachment_id]` |
| 2. Storage | `MediaService.upload_image` | File bytes, metadata | Attachment record in DB + object storage |
| 3. Linking | `MediaService.update_message_attachments` | `message_id`, `attachment_ids` | Message-attachment relationships |
| 4. Retrieval | `ConversationService._prepare_attachments_as_images` | `attachment_ids` | `Dict[str, Dict[str, Union[str, int]]]` with base64 data |
| 5. Context | `ConversationService._prepare_conversation_context_images` | `conversation_id`, `limit` | Historical images as base64 dict |
| 6. Execution | `AgentService.execute_stream` | `ChatContext` with images | Streaming AI responses with vision analysis |

**Sources**: [app/modules/conversations/conversation/conversation_service.py:1-1323](), [app/modules/conversations/conversations_router.py:1-622](), [app/modules/media/media_service.py]()