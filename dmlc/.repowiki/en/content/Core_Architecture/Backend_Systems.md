# Backend Systems for DML Framework

## Introduction

The **Backend Systems** in the Device Modeling Language (DML) framework constitute the final stage of the compilation pipeline. These systems transform fully analyzed DML code into C-based, executable artifacts to integrate seamlessly with the Simics simulation environment. As part of the backend responsibilities, the framework handles tasks such as C code generation, device structure serialization, runtime integration, and generation of debugging aids.

This page examines the architecture, workflows, and outputs of the backend. We include detailed diagrams, tables summarizing key information, and code snippets to clarify every stage of the backend's operation.

## Backend Architecture

The architecture of the backend consists of multiple layers that incrementally refine intermediate representations and produce final C output. Below is an overview of its components:

### Top-Level Architecture

```mermaid
flowchart TD
    subgraph "Input: Semantic Analysis Output"
        OBJECT_TREE["Object Tree<br/>(devices, methods, traits)"]
        TRAIT_INFO["Trait Metadata"]
        METHOD_NODES["Methods and Attributes"]
        DEVICE_STATE["Type Definitions<br/>Device State"]
    end

    subgraph "Intermediate Representation (IR)"
        CTREE["Intermediate Representation<br/>(ctree)"]
        IR_GEN["IR Generation<br/>(codegen.py)"]
    end

    subgraph "Code Generation Backend"
        CODEGEN_ORCH["C Code Generation Orchestration<br/>(c_backend.py)"]
        STRUCT_GEN["Device Structure Generator"]
        ATTR_GEN["Attribute Accessor Generator"]
        EVENT_GEN["Event and Hook Generators"]
    end

    subgraph "Runtime Integration"
        RUNTIME["Simics Runtime Interfaces<br/>(dmllib.h)"]
        SERIAL["Serialization<br/>Checkpoints"]
        POLY["Polymorphic Trait Handling"]
    end

    subgraph "Output Artifacts"
        C_FILE["C Implementation Files"]
        HEADER_FILE["C Header Files"]
        DEBUG_FILE["Debug Information Files"]
    end

    OBJECT_TREE --> IR_GEN
    TRAIT_INFO --> IR_GEN
    METHOD_NODES --> IR_GEN
    DEVICE_STATE --> IR_GEN

    IR_GEN --> CTREE
    CTREE --> CODEGEN_ORCH
    CODEGEN_ORCH --> STRUCT_GEN
    CODEGEN_ORCH --> ATTR_GEN
    CODEGEN_ORCH --> EVENT_GEN

    STRUCT_GEN --> C_FILE
    ATTR_GEN --> HEADER_FILE
    EVENT_GEN --> DEBUG_FILE

    RUNTIME --> STRUCT_GEN
    RUNTIME --> ATTR_GEN
    RUNTIME --> EVENT_GEN
```

### Backend Modules and Responsibilities

| Module                | Purpose                           | Key Functions                           |
|-----------------------|-----------------------------------|-----------------------------------------|
| `codegen.py`          | IR generation                    | `expression_dispatcher`, `method_instance` |
| `ctree.py`            | C-like IR abstraction            | `mkIf`, `mkWhile`, `mkCompound`, `read` |
| `c_backend.py`        | Backend orchestration            | `generate`, `print_device_substruct`    |
| `serialize.py`        | Serialization support            | `_serialize_simple_event_data`, `_get_value` |
| `traits.py`           | Trait handling                   | `CALL_TRAIT_METHOD`, `generate_attributes` |
| Simics `dmllib.h`     | Runtime library API definition   | `DML_ASSERT`, `_serialize_identity`     |

## Backend Workflow and Processes

### High-Level Backend Pipeline

The backend pipeline processes DML semantic outputs and produces multiple C artifacts, including implementation files, dynamic attribute handlers, and debugging data. Its stages are:

1. **IR Generation Stage:** Produces a simplified, C-like intermediate representation (`ctree.IR`) optimized for code translation.
2. **C Structure Generation:** Converts the device object tree and runtime state into C structures.
3. **Method Compilation:** Wraps input methods into Simics-compatible function signatures.
4. **Attribute Handling:** Creates getter/setter pairs for interacting with device state.
5. **Event/Hook Registrations:** Generates event triggers and after-on-hook callbacks.
6. **Output File Emission:** Writes all required `.c`, `.h`, and debug information files.

```mermaid
flowchart TD
    SEMANTIC_OUTPUT["Semantic Analyzed Input<br/>(object tree, traits, etc.)"]
    IR_GEN["IR Generation<br/>(ctree nodes)"]
    CODEGEN["Code Generation<br/>(device methods, attributes)"]
    STRUCT_GEN["Device Structure Generation"]
    SERIAL_GEN["Serialization Integration"]
    FILE_WRITE["C File Emission<br/>(*.c, *.h, device.g files)"]

    SEMANTIC_OUTPUT --> IR_GEN
    IR_GEN --> CODEGEN
    CODEGEN --> STRUCT_GEN
    CODEGEN --> SERIAL_GEN
    STRUCT_GEN --> FILE_WRITE
    SERIAL_GEN --> FILE_WRITE
```

---

### IR Generation

The first backend stage translates high-level DML constructs (e.g., traits, methods) into `ctree` nodes. This IR mirrors core C representation but includes abstractions for type-rich constructs such as traits and serialized objects.

#### IR Workflow

```mermaid
flowchart TD
    TREE["AST Tree<br/>(AST Nodes)"]
    EXP_DISP["Expression Dispatcher<br/>(codegen.py)"]
    NODE_MAP["Expression-to-IR Mapping"]
    STATEMENTS["Ctree Statements"]
    EXPRESSIONS["Ctree Expressions"]

    TREE --> EXP_DISP
    EXP_DISP --> NODE_MAP
    NODE_MAP --> STATEMENTS
    NODE_MAP --> EXPRESSIONS
```

#### Key IR Handlers

| AST Node     | Generator Function   | Output Node       |
|--------------|----------------------|-------------------|
| Method Call  | `codegen_call`       | `ctree.Call`      |
| If Statement | `mkIf`               | `ctree.If`        |
| For Loop     | `mkFor`              | `ctree.For`       |
| Binary Op    | `expr_binop()`       | `ctree.BinOp`     |

---

### Device Structure Generation

All device simulation state is packaged into a large C `struct`. Components like `banks`, `events`, `hooks`, and `state variables` are explicitly incorporated based on object type.

```mermaid
flowchart TD
    OBJECT_TREE["DML Object Tree"]
    PRINT_SUB["Substruct Printer"]
    TSTRUCT["C TStruct Generator"]
    SAVE["Persistent Storage"]
    EMIT["Emit Device Struct Headers"]

    OBJECT_TREE --> PRINT_SUB
    PRINT_SUB --> TSTRUCT
    TSTRUCT --> SAVE
    TSTRUCT --> EMIT
```

---

### C Code Generation (Methods)

C functions for DML methods are generated with `codegen_method_func` in the following workflow:

```mermaid
flowchart TD
    METHOD_AST["DML Method Def"]
    METHOD_FUNC["Generate Method IR"]
    FAILURE_HANDLE["Add Failure Handlers"]
    WRAP_FUNC["Wrap for Simics API"]
    OUTPUT_C["Output C Function"]
    
    METHOD_AST --> METHOD_FUNC
    METHOD_FUNC --> FAILURE_HANDLE
    FAILURE_HANDLE --> WRAP_FUNC
    WRAP_FUNC --> OUTPUT_C
```

Sample output for a DML method with getter logic:

```c
attr_value_t get_example_attr(conf_object *_obj, lang_void *aux) {
  attr_value_t v;
  // Runtime checks
  // Dynamic data retrieval
}
```

---

### Event and Hook Generation

```mermaid
flowchart TD
    AFTER_STMT["After Statements"]
    HOOK_INFO["Hook Metadata"]
    CALLBACKS["Generate Callbacks"]
    EMISSION["Emit Hook/Event Functions"]
    
    AFTER_STMT --> HOOK_INFO
    HOOK_INFO --> CALLBACKS
    CALLBACKS --> EMISSION
```

---

### Backend Output Files

| File                | Purpose                              | Example Content                     |
|---------------------|--------------------------------------|-------------------------------------|
| `device-dml.c`      | Implementation for methods, events   | Method bodies, trait dispatch       |
| `device-dml.h`      | Declarations for traits, methods     | Struct typedefs, prototypes         |
| `device.g`          | Debug mapping file (optional)        | Debug metadata output               |
| `device-struct.h`   | Device memory & runtime state struct | State definitions                   |

---

## Conclusion

The backend systems of the DML framework combine advanced code generation techniques with Simics runtime integrations, providing a robust solution for translating high-level device models into efficient, executable C. Its modular architecture ensures extensibility, while its outputs, such as dynamic structure handling, interactive debugging aids, and efficient serialization, ensure the usability of compiled device simulators. The backend stands as a critical component in the pipeline from device modeling to system simulation.