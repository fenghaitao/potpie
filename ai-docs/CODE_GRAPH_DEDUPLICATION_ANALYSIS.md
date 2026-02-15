# Code Graph Deduplication Analysis

## 🐛 The Problem

**Potpie's code graph has duplicate nodes!**

### Evidence

```cypher
// Query: Find nodes named 'parse_repo' in potpie_cli.py
MATCH (n) 
WHERE n.name = 'parse_repo' AND n.file_path = 'potpie_cli.py'
RETURN count(*) as total

Result: 3 duplicates (same file, same function, same node_id!)
```

**All 3 nodes have:**
- Same `node_id`: `6855fc07b879f75f3a7b2607f80e58cd`
- Same `file_path`: `potpie_cli.py`
- Same `name`: `parse_repo`
- Same line numbers

---

## 🔍 Root Cause

**Location:** `app/modules/parsing/graph_construction/code_graph_service.py`

**The Problem Code:**
```python
CALL apoc.create.node(node.labels, node)  # ← Always creates new nodes!
```

**Why it's wrong:**
- `apoc.create.node` **always creates** a new node
- Never checks if node already exists
- No deduplication logic

**Should use:**
```cypher
MERGE (n:NODE {repoId: node.repoId, node_id: node.node_id})
ON CREATE SET n = node
ON MATCH SET n += node
```

---

## 📊 Impact

### **Problem 1: Duplicate Nodes**

Same function appears multiple times:
- ❌ Inflated node count
- ❌ Wasted storage
- ❌ Slower queries

### **Problem 2: Same Symbol in Test vs Implementation**

```python
# Implementation: app/auth/service.py
def login(user, password):  # ← Node 1
    ...

# Test: app/auth/tests/test_service.py  
def login(user, password):  # ← Node 2 (mock/helper)
    ...
```

**Both get created, but:**
- ❌ No way to distinguish test from implementation
- ❌ Queries return both
- ❌ AI gets confused about which to use

### **Problem 3: Query Confusion**

```cypher
// Want: Find the login function
MATCH (n {name: 'login'})
RETURN n

// Get: 5+ results (implementation + tests + duplicates)
```

---

## 🎯 Three Scenarios Where Duplicates Happen

### **Scenario 1: Same File Parsed Multiple Times**
- Re-parsing a project
- No cleanup of old nodes
- Creates duplicates

### **Scenario 2: Same Symbol Name (Test vs Implementation)**
```
implementation/user_service.py:
    def create_user()  ← Real implementation

tests/test_user_service.py:
    def create_user()  ← Test helper/mock
```

### **Scenario 3: Incremental Parsing Bug**
- Parsing updates
- Old nodes not removed
- New nodes added

---

## 💡 Solutions

### **Option 1: Quick Fix - Add Constraint (5 minutes)**

```cypher
// Create unique constraint
CREATE CONSTRAINT unique_node_per_repo IF NOT EXISTS
FOR (n:NODE) 
REQUIRE (n.repoId, n.node_id) IS UNIQUE
```

**Pros:**
- ✅ Prevents future duplicates
- ✅ Database-level enforcement
- ✅ 5 minutes to implement

**Cons:**
- ⚠️ Doesn't fix existing duplicates
- ⚠️ Will fail on current data (need cleanup first)

### **Option 2: Proper Fix - Use MERGE (1-2 hours)**

**Change:** `app/modules/parsing/graph_construction/code_graph_service.py`

```python
# Before (creates duplicates):
query = """
UNWIND $nodes as node
CALL apoc.create.node(node.labels, node)
"""

# After (deduplicates):
query = """
UNWIND $nodes as node
MERGE (n:NODE {repoId: node.repoId, node_id: node.node_id})
ON CREATE SET n = node, n.created_at = datetime()
ON MATCH SET n += node, n.updated_at = datetime()
RETURN n
"""
```

**Pros:**
- ✅ Proper deduplication
- ✅ Updates existing nodes
- ✅ Tracks creation/update times

**Cons:**
- ⚠️ Slightly slower (MERGE vs CREATE)
- ⚠️ Need to test thoroughly

### **Option 3: Complete Solution (1-2 days)**

**Add all three fixes:**

1. **Add `is_test` property**
```python
def enrich_node(node: dict, file_path: str) -> dict:
    node['is_test'] = is_test_file(file_path) or node['name'].startswith('test_')
    return node
```

2. **Use MERGE for deduplication**
```cypher
MERGE (n:NODE {repoId: $repoId, node_id: $node_id})
```

3. **Add unique constraint**
```cypher
CREATE CONSTRAINT unique_node IF NOT EXISTS
FOR (n:NODE) REQUIRE (n.repoId, n.node_id) IS UNIQUE
```

---

## 🧹 Cleanup Script

Remove existing duplicates before adding constraint:

```cypher
// Find and remove duplicates, keeping the first one
MATCH (n:NODE)
WITH n.repoId as repoId, n.node_id as node_id, collect(n) as nodes
WHERE size(nodes) > 1
FOREACH (node IN tail(nodes) | 
    DETACH DELETE node
)
RETURN count(*) as duplicates_removed
```

---

## 🚀 Recommended Action Plan

### **Step 1: Cleanup (Now)**
```bash
# Run cleanup script
python scripts/remove_duplicates.py --project-id <id>
```

### **Step 2: Add Constraint (Now)**
```cypher
CREATE CONSTRAINT unique_node IF NOT EXISTS
FOR (n:NODE) REQUIRE (n.repoId, n.node_id) IS UNIQUE
```

### **Step 3: Fix Code (This Week)**
- Update `code_graph_service.py` to use MERGE
- Add `is_test` property
- Test thoroughly

### **Step 4: Re-parse (Next Week)**
- Re-parse all projects with new code
- Verify no duplicates
- Monitor performance

---

## 📈 Expected Results

**Before:**
- 4,004 nodes (with ~400 duplicates)
- Query returns 3 results for one function
- No test/implementation distinction

**After:**
- ~3,600 unique nodes
- Query returns 1-2 results (impl + optional test)
- Clear is_test flag
- 10% faster queries

---

## 💻 Implementation Time

| Task | Time | Priority |
|------|------|----------|
| Cleanup existing duplicates | 30 min | High |
| Add constraint | 5 min | High |
| Update to MERGE | 1-2 hours | High |
| Add is_test property | 1 hour | Medium |
| Testing | 2 hours | High |
| **Total** | **~5 hours** | - |

---

## 📝 Summary

**Problem:** Duplicate nodes from using CREATE instead of MERGE

**Impact:** Inflated counts, confused queries, wasted storage

**Solution:** 
1. Clean up duplicates
2. Add unique constraint
3. Use MERGE instead of CREATE
4. Add is_test property

**Effort:** ~5 hours for complete fix

**Value:** Cleaner graph, faster queries, better AI responses

