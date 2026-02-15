# Potpie Agents Guide - "Choose Your Expert"

Complete guide to all 9 specialized AI agents in Potpie.

---

## 🎯 Quick Reference

| Agent | Best For | Code Changes | Tools | Complexity |
|-------|----------|--------------|-------|------------|
| **Codebase Q&A** | Understanding code | ❌ No | 16+ | ⭐⭐⭐ |
| **Code Generation** | Writing/modifying code | ✅ Yes | 30+ | ⭐⭐⭐⭐⭐ |
| **Debugging** | Finding & fixing bugs | ✅ Yes | 16+ | ⭐⭐⭐⭐ |
| **General Purpose** | Simple questions | ❌ No | 2 | ⭐ |
| **Unit Testing** | Writing unit tests | ✅ Yes | 7+ | ⭐⭐⭐ |
| **Integration Testing** | Writing integration tests | ✅ Yes | 7+ | ⭐⭐⭐ |
| **Blast Radius** | Impact analysis | ❌ No | 9+ | ⭐⭐ |
| **Low-Level Design** | Design docs | ✅ Yes | 11+ | ⭐⭐⭐ |
| **SWEB Debug** | Complex debugging | ✅ Yes | 16+ | ⭐⭐⭐⭐⭐ |

---

## 📖 Detailed Agent Profiles

### 1. 🔍 **Codebase Q&A Agent** (Most Popular)

**Purpose:** Understand how your code works

**Best For:**
- "How does authentication work?"
- "Explain the payment flow"
- "What does this function do?"
- "Where is user data stored?"

**Key Features:**
- ✅ **Systematic 5-step exploration**
- ✅ **Knowledge graph queries**
- ✅ **Code analysis tools**
- ✅ **Clear, structured answers**

**Workflow:**
1. Analyze your question
2. Query knowledge graph
3. Search relevant code
4. Explore relationships
5. Synthesize answer

**Tools (16+):**
- Intelligent code graph search
- File content retrieval
- Code structure analysis
- Bash commands
- Knowledge graph queries

**Example:**
```
You: "How does user authentication work?"

Agent:
1. Searches for "auth" in knowledge graph
2. Finds AuthService, auth_router, JWT modules
3. Analyzes authentication flow
4. Explains: "Authentication uses JWT tokens with Firebase..."
```

---

### 2. 💻 **Code Generation Agent**

**Purpose:** Write or modify code

**Best For:**
- "Add rate limiting to the API"
- "Create a new REST endpoint"
- "Refactor UserService"
- "Implement caching"

**Key Features:**
- ✅ **All Q&A tools PLUS code modification**
- ✅ **Change tracking with git-style diffs**
- ✅ **Code verification**
- ✅ **Multi-file changes**

**Workflow:**
1. Understand requirements
2. Analyze existing code
3. Plan changes
4. Generate code
5. Show diffs
6. Apply changes
7. Verify

**Tools (30+):**
- Everything from Q&A agent
- **Code Changes Manager** (track modifications)
- **show_diff** (display changes)
- File creation/modification

**Example:**
```
You: "Add request logging middleware"

Agent:
1. Analyzes current middleware setup
2. Plans: Create logging_middleware.py, update main.py
3. Generates code with proper integration
4. Shows diffs:
   + logging_middleware.py (new file)
   ~ main.py (3 lines changed)
5. Applies changes
```

---

### 3. 🐛 **Debugging Agent**

**Purpose:** Find and fix bugs

**Best For:**
- "Fix: User can't login with special chars in password"
- "Why is API returning 500?"
- "Memory leak in worker process"

**Key Features:**
- ✅ **Systematic debugging process**
- ✅ **Root cause analysis**
- ✅ **Fix suggestions**
- ✅ **Can apply fixes**

**Workflow:**
1. Reproduce the bug
2. Analyze symptoms
3. Trace code execution
4. Identify root cause
5. Suggest fixes
6. (Optional) Apply fix

**Tools (16+):**
- Q&A tools
- Code modification tools
- Bash commands for testing
- Log analysis

**Example:**
```
You: "Users get 500 error when username has spaces"

Agent:
1. Searches auth code
2. Finds validation logic
3. Tests: "john doe" → SQL error
4. Root cause: Missing input sanitization
5. Fix: Add validation + sanitization
6. Verifies fix works
```

---

### 4. 🤖 **General Purpose Agent** (Simplest)

**Purpose:** Simple questions that don't need code context

**Best For:**
- "What is rate limiting?"
- "Explain REST vs GraphQL"
- "Best practices for API design"

**Key Features:**
- ❌ **No code access** (lightweight)
- ✅ **Fast responses**
- ✅ **General knowledge**

**Tools (2):**
- Think (reasoning)
- Web search (optional)

**When to use:**
- Conceptual questions
- No code context needed
- General programming help

**Example:**
```
You: "What's the difference between JWT and sessions?"

Agent: (Explains without accessing your code)
```

---

### 5. ✅ **Unit Testing Agent**

**Purpose:** Write unit tests

**Best For:**
- "Write tests for UserService.create_user"
- "Add test coverage for auth module"
- "Generate pytest tests"

**Key Features:**
- ✅ **Analyzes code to test**
- ✅ **Generates comprehensive tests**
- ✅ **Follows project conventions**
- ✅ **Mocking & fixtures**

**Workflow:**
1. Analyze target code
2. Identify test cases
3. Generate test file
4. Add assertions
5. Create fixtures if needed

**Tools (7+):**
- Code analysis
- Code modification
- Test framework detection
- Bash (run tests)

**Example:**
```
You: "Write tests for parse_repo function"

Agent:
1. Analyzes parse_repo()
2. Identifies: success case, error cases, edge cases
3. Generates test_parse_repo.py with:
   - test_parse_repo_success()
   - test_parse_repo_invalid_path()
   - test_parse_repo_empty_directory()
4. Adds pytest fixtures
```

---

### 6. 🔗 **Integration Testing Agent**

**Purpose:** Write integration/E2E tests

**Best For:**
- "Test the entire auth flow"
- "Write API endpoint tests"
- "Test database interactions"

**Key Features:**
- ✅ **Tests multiple components**
- ✅ **Real dependencies**
- ✅ **Setup/teardown**
- ✅ **API/database testing**

**Workflow:**
1. Analyze full flow
2. Identify integration points
3. Generate test with setup
4. Add teardown
5. Test real interactions

**Tools (7+):**
- Same as Unit Testing
- Database tools
- API testing

**Example:**
```
You: "Test user registration flow end-to-end"

Agent:
1. Maps: API → Service → Database
2. Generates test that:
   - Sets up test database
   - Calls /register endpoint
   - Verifies DB entry
   - Checks email sent
   - Cleans up
```

---

### 7. 💥 **Blast Radius Agent**

**Purpose:** Impact analysis before changes

**Best For:**
- "What breaks if I change UserService?"
- "Impact of renaming this function?"
- "What depends on this class?"

**Key Features:**
- ✅ **Dependency analysis**
- ✅ **Find all usages**
- ✅ **Risk assessment**
- ✅ **Change planning**

**Workflow:**
1. Analyze target code
2. Find all dependencies
3. Map impact
4. Assess risk
5. Suggest safe changes

**Tools (9+):**
- Knowledge graph queries
- Dependency analysis
- Code search

**Example:**
```
You: "What's the blast radius of changing AuthService.login signature?"

Agent:
1. Finds all calls to login()
2. Identifies:
   - auth_router.py (3 calls)
   - test_auth.py (12 calls)
   - middleware.py (1 call)
3. Risk: MEDIUM (16 changes needed)
4. Suggests: Add new parameter with default value
```

---

### 8. 📐 **Low-Level Design Agent**

**Purpose:** Create detailed design documents

**Best For:**
- "Design a caching layer"
- "Create API specification for user service"
- "Design database schema for messaging"

**Key Features:**
- ✅ **Detailed design docs**
- ✅ **Code snippets**
- ✅ **Diagrams (text)**
- ✅ **Implementation guide**

**Workflow:**
1. Gather requirements
2. Analyze existing code
3. Create design document
4. Add examples
5. Suggest implementation

**Tools (11+):**
- Code analysis
- File creation
- Documentation tools

**Example:**
```
You: "Design a rate limiting system"

Agent creates document with:
1. Requirements
2. Architecture (Redis-based)
3. Code examples
4. Database schema
5. API contracts
6. Error handling
7. Testing strategy
```

---

### 9. 🔬 **SWEB Debug Agent** (Most Advanced)

**Purpose:** Complex, multi-step debugging

**Best For:**
- Production issues
- Complex bugs
- Performance problems
- Multi-service debugging

**Key Features:**
- ✅ **Most sophisticated debugging**
- ✅ **Multi-step reasoning**
- ✅ **Hypothesis testing**
- ✅ **Detailed investigation**

**Workflow:**
1. Understand problem deeply
2. Form hypotheses
3. Test each hypothesis
4. Narrow down root cause
5. Verify fix
6. Document findings

**Tools (16+):**
- Full debugging toolkit
- Performance analysis
- Log analysis
- Multi-file investigation

**Example:**
```
You: "API is 10x slower in production vs dev"

Agent:
1. Hypothesis 1: Database queries slow
   → Checks query logs → Not the issue
2. Hypothesis 2: Network latency
   → Tests endpoints → Normal
3. Hypothesis 3: Caching disabled
   → Checks config → FOUND IT!
4. Redis not connected in prod
5. Provides fix + verification
```

---

## 🎯 How to Choose the Right Agent

### Decision Tree:

```
Do you need code changes?
├─ NO → Do you need codebase context?
│        ├─ NO → General Purpose
│        └─ YES → Do you need impact analysis?
│                 ├─ YES → Blast Radius
│                 └─ NO → Codebase Q&A
│
└─ YES → What type of change?
         ├─ Writing tests → Unit Testing or Integration Testing
         ├─ Design doc → Low-Level Design
         ├─ Bug fix → Debugging (or SWEB Debug if complex)
         └─ Feature/refactor → Code Generation
```

### Quick Guide:

- **"How does X work?"** → Codebase Q&A
- **"Add feature Y"** → Code Generation
- **"Fix bug Z"** → Debugging
- **"What breaks if I change X?"** → Blast Radius
- **"Write tests for X"** → Unit/Integration Testing
- **"Design feature Y"** → Low-Level Design
- **"Why is prod slow?"** → SWEB Debug
- **"What is X?"** (no code context) → General Purpose

---

## 💡 Pro Tips

### **1. Agent Chaining**

Use multiple agents in sequence:

```
1. Blast Radius → "What's impacted by changing UserService?"
2. Low-Level Design → "Design the refactored UserService"
3. Code Generation → "Implement the design"
4. Unit Testing → "Add tests for new UserService"
```

### **2. When to Use SWEB vs Regular Debug**

| Use Case | Agent |
|----------|-------|
| Simple bug (clear error message) | Debugging |
| Complex investigation needed | SWEB Debug |
| Production issue | SWEB Debug |
| Performance problem | SWEB Debug |
| Multi-service issue | SWEB Debug |

### **3. Testing Strategy**

- **Unit tests** → Unit Testing Agent (fast, isolated)
- **API tests** → Integration Testing Agent (real endpoints)
- **Full flow** → Integration Testing Agent (E2E)

---

## 📊 Capabilities Matrix

| Feature | Q&A | CodeGen | Debug | General | Unit Test | Int Test | Blast | LLD | SWEB |
|---------|-----|---------|-------|---------|-----------|----------|-------|-----|------|
| Read code | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Modify code | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Knowledge graph | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Bash commands | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Multi-step | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Change tracking | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ |

---

## 🚀 Getting Started

1. **Start with Q&A** to understand code
2. **Use Blast Radius** before changes
3. **CodeGen** for implementation
4. **Testing agents** for coverage
5. **Debug/SWEB** when things break

---

## 📝 Summary

Potpie has 9 specialized agents:

1. **Codebase Q&A** - Understand code (most versatile)
2. **Code Generation** - Write/modify code (most powerful)
3. **Debugging** - Fix bugs
4. **General Purpose** - Simple questions (no code context)
5. **Unit Testing** - Write unit tests
6. **Integration Testing** - Write integration tests
7. **Blast Radius** - Impact analysis
8. **Low-Level Design** - Design documents
9. **SWEB Debug** - Complex debugging (most advanced)

**Choose based on your task**, and don't hesitate to chain multiple agents for complex workflows!

