# Building Relationships Between Implementation and Tests

## 🎯 Current State Analysis

### What Already Exists ✅

**Relationship Type:** `REFERENCES`
- Tests already link to implementation via imports/function calls
- Example: `test_gvisor_setup` → `is_gvisor_available`
- **Count:** 7,206 REFERENCES relationships (many are test→impl)

**Problem:** 
- ❌ No distinction between test and non-test references
- ❌ Can't easily find "all tests for function X"
- ❌ Can't measure test coverage
- ❌ Mixed with regular code references

---

## 💡 Proposed Solution: Multi-Level Relationship Strategy

### **Level 1: Mark Test Nodes** (Foundation)

Add properties to distinguish test nodes:

```python
# Node properties
{
    "node_id": "abc123",
    "name": "test_auth_router",
    "file_path": "app/modules/auth/tests/test_auth_router.py",
    "is_test": True,              # ← NEW
    "test_type": "unit",          # ← NEW: unit|integration|e2e
    "test_framework": "pytest"    # ← NEW
}
```

**Detection Logic:**
```python
def is_test_node(file_path: str, name: str) -> dict:
    """Detect if node is a test."""
    is_test = (
        "/test" in file_path or
        "/tests/" in file_path or
        file_path.startswith("test_") or
        name.startswith("test_")
    )
    
    test_type = None
    if is_test:
        if "integration" in file_path or "integration" in name:
            test_type = "integration"
        elif "e2e" in file_path or "end_to_end" in name:
            test_type = "e2e"
        else:
            test_type = "unit"
    
    return {
        "is_test": is_test,
        "test_type": test_type,
        "test_framework": detect_framework(file_path)
    }
```

### **Level 2: Specialized Test Relationships**

Create specific relationship types:

```cypher
// 1. Direct test relationship
(test:NODE {is_test: true})-[:TESTS]->(impl:NODE {is_test: false})

// 2. Setup/teardown relationships  
(test:NODE)-[:USES_FIXTURE]->(fixture:NODE)

// 3. Mock relationships
(test:NODE)-[:MOCKS]->(impl:NODE)

// 4. Assert relationships
(test:NODE)-[:ASSERTS_ON]->(impl:NODE)
```

### **Level 3: Inference-Based Relationships**

Use heuristics and AI to infer relationships:

#### **Pattern 1: Naming Convention**
```python
# Test: test_parse_repo()
# Implementation: parse_repo()
→ Create TESTS relationship
```

#### **Pattern 2: Import Analysis**
```python
# In test_auth_router.py:
from app.modules.auth.auth_router import auth_router

→ test_auth_router.py TESTS auth_router.py
```

#### **Pattern 3: Function Call Analysis**
```python
def test_create_user():
    result = create_user("john")  # ← Function call
    assert result.name == "john"   # ← Assertion
    
→ test_create_user TESTS create_user
→ test_create_user ASSERTS_ON User.name
```

---

## 🔧 Implementation Plan

### **Phase 1: Foundation (2-3 hours)**

Add test metadata to nodes during parsing.

### **Phase 2: Relationship Creation (4-5 hours)**

Build TESTS relationships from:
- Import analysis
- Naming conventions
- Call analysis

### **Phase 3: Query Enhancements (1-2 hours)**

Enable powerful queries:

```cypher
// Find all tests for a function
MATCH (test:NODE {is_test: true})-[:TESTS]->(impl:NODE {name: 'create_user'})
RETURN test.name, test.file_path, test.test_type

// Find untested functions
MATCH (impl:NODE {is_test: false, repoId: $project_id})
WHERE NOT (impl)<-[:TESTS]-(:NODE {is_test: true})
RETURN impl.name, impl.file_path

// Test coverage statistics
MATCH (impl:NODE {is_test: false, repoId: $project_id})
OPTIONAL MATCH (impl)<-[:TESTS]-(test:NODE {is_test: true})
WITH impl, count(test) as num_tests
RETURN 
    count(impl) as total_functions,
    sum(CASE WHEN num_tests > 0 THEN 1 ELSE 0 END) as tested_functions,
    sum(num_tests) as total_tests
```

---

## 🎯 Benefits

### **For Developers:**
- ✅ See all tests for a function
- ✅ Find untested code
- ✅ Understand test coverage
- ✅ Impact analysis: "What breaks if I change this?"

### **For AI Agents:**
- ✅ Better context when debugging
- ✅ Can suggest where tests are missing
- ✅ Can generate tests for uncovered code
- ✅ Can analyze test patterns

### **For Code Quality:**
- ✅ Measure test coverage
- ✅ Identify risky changes (many tests affected)
- ✅ Track testing trends over time

---

## 📊 Example: Complete Test Graph

```
File: app/modules/auth/auth_service.py
┌──────────────────────────────────────┐
│ AuthService                          │
│ is_test: false                       │
└─────────────┬────────────────────────┘
              │
              │ ← TESTED BY
              │
┌─────────────┴────────────────────────┐
│ File: app/modules/auth/tests/        │
│       test_auth_service.py           │
│ is_test: true                        │
└──┬───────────────────────────────────┘
   │
   ├─ test_login()           [:TESTS]→ AuthService.login()
   ├─ test_register()        [:TESTS]→ AuthService.register()
   ├─ test_logout()          [:TESTS]→ AuthService.logout()
   ├─ test_refresh_token()   [:TESTS]→ AuthService.refresh_token()
   └─ test_invalid_creds()   [:TESTS]→ AuthService.login()
                            [:ASSERTS_ON]→ AuthException

Coverage: 4/5 methods tested (80%)
Test Types: 100% unit tests
Assertions: 12 total
```

---

## 🚀 Action Items

### **Immediate:**
1. Add `is_test`, `test_type`, `test_framework` properties to nodes
2. Create `TestRelationshipBuilder` class
3. Integrate into parsing pipeline

### **Short-term:**
4. Create TESTS relationships from imports
5. Add naming-based inference
6. Test coverage queries
7. Update agents to use test info

### **Medium-term:**
8. AI-assisted relationship inference
9. Coverage dashboard
10. Test generation suggestions

---

## 📝 Summary

**The Strategy:**
1. **Mark** test nodes with properties
2. **Create** specialized TESTS relationships
3. **Infer** relationships from imports, naming, calls
4. **Enable** powerful queries and AI features

**Effort:** ~8-10 hours for full implementation

**Value:** Massive! Enables test coverage analysis, impact analysis, better AI assistance

