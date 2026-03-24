# Development and Testing  

## Introduction  

This documentation provides an in-depth guide to the "Development and Testing" workflows for the DML (Device Modeling Language) framework. It is intended for developers and contributors working on device models or the DML compiler. The guide highlights key development practices, testing mechanisms, automated porting workflows, and the infrastructure supporting DML's lifecycle: from source to execution in the Simics environment.  

The testing framework, porting tools, and compiler infrastructure ensure backward compatibility, reliable code generation, and accurate runtime functionality. This document is organized to provide seamless access to workflow overviews, tool architectures, testing systems, and functional details drawn directly from source.  

---

## Development Workflow  

### Device Model Development  

Developing device models follows these steps to ensure correctness and conformance:  

```mermaid  
flowchart TD  
    START["Author DML Code<br/>(.dml files)"]  
    TEST_ANNOTATION["Add Test Annotations<br/>/// ERROR, /// WARNING"]  
    RUN_TESTS["Run Test Suite<br/>tests.py"]  
    DEBUG["Debug Failures<br/>Review Logs"]  
    VALIDATION["Validate in Simics<br/>Compile and Integrate"]  

    START --> TEST_ANNOTATION  
    TEST_ANNOTATION --> RUN_TESTS  
    RUN_TESTS --> DEBUG  
    DEBUG --> |"Iterate"| START  
    RUN_TESTS --> |"All Tests Pass"| VALIDATION  
    style START fill:#e1f5ff  
    style RUN_TESTS fill:#fff4e1  
    style VALIDATION fill:#c6ffe1  
```  

### Compiler Development  

Compiler development emphasizes maintaining consistency across the DML pipeline:  

```mermaid  
flowchart TD  
    MODIFY["Modify Compiler<br/>(dml/*.py)"]  
    RUN_UNIT_TESTS["Run Unit Tests<br/>(*_test.py)"]  
    RUN_INTEG_TESTS["Run Integration Tests<br/>(tests.py)"]  
    CHECK_ARTIFACTS["Update Generated Artifacts<br/>Documentation, Tables"]  
    BUILD_OUTPUT["Build Outputs<br/>(Makefile)"]  
    DEBUG_ISSUES["Fix Builds or Failures"]  

    MODIFY --> RUN_UNIT_TESTS  
    RUN_UNIT_TESTS --> RUN_INTEG_TESTS  
    RUN_INTEG_TESTS --> CHECK_ARTIFACTS  
    CHECK_ARTIFACTS --> BUILD_OUTPUT  
    BUILD_OUTPUT --> |"Fix Failures"| DEBUG_ISSUES  
    DEBUG_ISSUES --> MODIFY  
    style MODIFY fill:#ffe1e1  
    style BUILD_OUTPUT fill:#fddfff  
```  

---

## Tool Architectures  

The DML development framework integrates multiple tools to support testing, porting, building, and generating artifacts.  

### Test Infrastructure  

```mermaid  
flowchart TD  
    TEST_FRAMEWORK["Test Framework"] --> TEST_FILES["Test Cases<br/>(test/*.dml)"]  
    TEST_FRAMEWORK --> SCRATCH_DIR["Temporary Outputs<br/>(scratch/)"]  
    TEST_RUNNER["Runner API<br/>BaseTestCase, CTestCase"] --> LOG["Logger Outputs"]  

    TEST_FILES -.-> |"Validated by"| LOG  
    SCRATCH_DIR -.-> |"Stores"| LOG  

    style TEST_FRAMEWORK fill:#f4fcff  
    style LOG fill:#fce1e1  
```  

### Porting Framework  

```mermaid  
flowchart TD  
    PORT_TOOL["Porting Tool<br/>(port_dml.py)"] --> TRANSFORMS["Transformation<br>Classes"]  
    FILE_PROCESS["File Processor<br/>(SourceFile)"] --> TRANSFORMS  

    TRANSFORMS --> MIGRATIONS["Migration Scripts<br>(/// Porting Tags)"]  

    MIGRATIONS -.-> |"Validates 1.2 - 1.4"| FILE_PROCESS  

    style PORT_TOOL fill:#fbfdff  
    style FILE_PROCESS fill:#eef2f5  
```  

---

## Test Framework  

### Architecture  

The test framework organizes functionality using object-oriented extensions:  

```mermaid  
classDiagram  
    class BaseTestCase {  
        +run_test()  
        +pr()  
        +setup_sandbox()  
    }  

    class DMLFileTestCase {  
        +run_dmlc()  
        -test_flags()  
        -verify_dmlc_messages()  
    }  

    class CTestCase {  
        +run_cc()  
        +run_linker()  
        +run_simics()  
    }  

    BaseTestCase <|-- DMLFileTestCase  
    DMLFileTestCase <|-- CTestCase  
```  

### Stages  

The following stages define the test pipeline:  

```mermaid  
flowchart TD  
    SOURCE["Source File Input"] --> PARSE_ANNOTATION["Parse Annotations"]  
    PARSE_ANNOTATION --> RUN_DMLC["Run Compiler"]  
    RUN_DMLC --> CHECK_WARNINGS["Verify Compiler Logs"]  

    COMPILE["Compile Generated files"] --> LINK["Run Simics Test Modules"]  

```  

--- 

### Testing Workflow  

