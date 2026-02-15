# AI-Generated Documentation

This folder contains comprehensive documentation generated during AI-assisted development sessions exploring Potpie's architecture, design decisions, and implementation details.

---

## 📚 Documentation Index

### **Architecture & Design**

#### **AGENTS_GUIDE.md** (12K)
Complete guide to all 9 specialized AI agents in Potpie:
- Detailed profiles of each agent (Q&A, CodeGen, Debug, Testing, etc.)
- When to use which agent
- Capabilities comparison matrix
- Example workflows
- Agent chaining strategies

**Key Topics:** Agent selection, multi-agent workflows, tool usage

---

#### **WHY_REDIS_FOR_STREAMING.md** (7.0K)
Deep dive into why Redis is needed for streaming despite OpenAI already providing streaming:
- Cross-process communication problem
- Architecture comparison (Web UI vs CLI)
- Timing breakdown (millisecond-by-millisecond)
- Alternative solutions analysis
- Redis Streams vs other options

**Key Topics:** Process architecture, streaming, real-time communication

---

#### **IMPLEMENTATION_TEST_RELATIONSHIPS.md** (6.4K)
Design document for building relationships between tests and implementation code:
- Multi-level relationship strategy
- Test node properties (`is_test`, `test_type`, `test_framework`)
- Specialized relationships (TESTS, USES_FIXTURE, MOCKS, ASSERTS_ON)
- Inference patterns (naming, imports, calls, AI-assisted)
- Implementation plan (3 phases, ~8-10 hours)
- Query examples for test coverage analysis

**Key Topics:** Knowledge graph design, test coverage, code relationships

---

#### **CODE_GRAPH_DEDUPLICATION_ANALYSIS.md** (5.7K)
Analysis of duplicate node issue in the code graph:
- Evidence of duplicates (same function appearing 3x)
- Root cause (`apoc.create.node` vs `MERGE`)
- Impact analysis (queries, storage, AI confusion)
- Three solution options (quick fix, proper fix, complete solution)
- Cleanup scripts
- Implementation time estimates

**Key Topics:** Graph database optimization, data quality, deduplication

---

### **Setup & Configuration**

#### **RUNNING_WITHOUT_DOCKER.md** (Currently being recreated)
Guide to running Potpie with minimal or no Docker containers:
- Three setup options (Hybrid, CLI-only, All Local)
- Using Neo4j Desktop instead of Docker Neo4j
- Minimal Docker configuration (1-2 containers vs 3)
- Native PostgreSQL installation
- CLI-only mode (no Redis needed)

**Key Topics:** Local development, Docker alternatives, minimal setups

---

### **Helper Files**

#### **docker-compose.minimal.yaml** (1.5K)
Minimal Docker Compose configuration for hybrid setup:
- PostgreSQL container (with proxy config)
- Redis container (optional, for Web UI)
- No Neo4j (use Desktop instead)
- Health checks and auto-restart

**Use Case:** Running with Neo4j Desktop + minimal Docker

---

#### **setup_with_neo4j_desktop.sh** (3.3K)
Automated setup script for hybrid configuration:
- Checks Neo4j Desktop connection
- Starts minimal Docker services
- Runs database migrations
- Validates all services
- Provides next steps

**Use Case:** Quick setup with Neo4j Desktop

---

## 🎯 Quick Navigation

### **Want to understand...**

| Topic | Read This |
|-------|-----------|
| Which agent to use | AGENTS_GUIDE.md |
| Why Potpie needs Redis | WHY_REDIS_FOR_STREAMING.md |
| How to add test coverage tracking | IMPLEMENTATION_TEST_RELATIONSHIPS.md |
| Why there are duplicate nodes | CODE_GRAPH_DEDUPLICATION_ANALYSIS.md |
| How to run without full Docker | RUNNING_WITHOUT_DOCKER.md |

### **Want to do...**

| Task | Use This |
|------|----------|
| Set up with Neo4j Desktop | setup_with_neo4j_desktop.sh |
| Run minimal Docker | docker-compose.minimal.yaml |
| Understand agent capabilities | AGENTS_GUIDE.md → Capabilities Matrix |
| Fix duplicate nodes | CODE_GRAPH_DEDUPLICATION_ANALYSIS.md → Solutions |
| Design test relationships | IMPLEMENTATION_TEST_RELATIONSHIPS.md → Implementation Plan |

---

## 📊 Documentation Stats

- **Total Size:** ~43KB
- **Total Documents:** 7 files
- **Coverage:** Architecture, design, setup, troubleshooting
- **Generated:** 2026-02-14 (AI-assisted session)

---

## 🔄 Maintenance

These documents capture design decisions and architectural insights. Update them when:
- Architecture changes (e.g., new agents added)
- Implementation details change (e.g., switching databases)
- Issues are resolved (e.g., deduplication fixed)
- New patterns emerge (e.g., better agent workflows)

---

## 💡 How to Use This Documentation

1. **Browse by topic** - Use the Quick Navigation above
2. **Read sequentially** - Start with AGENTS_GUIDE.md for overview
3. **Reference as needed** - Search for specific topics
4. **Update when relevant** - Keep docs in sync with code

---

## 📝 Contributing

When adding new AI-generated documentation:
1. Place files in this folder
2. Update this README with description
3. Add to Quick Navigation
4. Keep file naming consistent (SCREAMING_SNAKE_CASE.md)

