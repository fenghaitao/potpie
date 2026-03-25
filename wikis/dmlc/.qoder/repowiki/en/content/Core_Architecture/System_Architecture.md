# System Architecture

## Introduction

This document outlines the **System Architecture** of the `dml` (Device Modeling Language) compiler. It provides an in-depth view of its modular design, key components, and data flow. The purpose of this architecture is to streamline diagnostics, error handling, and AI-assisted analysis within the DML compilation process. Leveraging structured error data, the system enables both human and AI-based tools to debug, categorize, and correct code more efficiently.

## Core Objectives

The system architecture is centered around the following primary objectives:

1. **Modular Design:** Ensure scalability and maintainability with a clear separation of concerns.
2. **AI-Driven Diagnostics:** Enable AI-assisted code corrections by capturing rich, structured diagnostic data.
3. **Error Categorization:** Handle 199 specific types of warnings and errors, hierarchically categorized into fix strategies.
4. **Extensibility:** Easily incorporate new diagnostics, improve error suggestions, and integrate future capabilities like automation.

---

## System Components Overview

### High-Level Design

The system architecture is modularized into the following core components:

1. **Compiler Core Modules:**
   - Core diagnostic logic resides in `py/dml/ai_diagnostics.py`.
   - Critical functionality in `py/dml/logging.py` and `py/dml/dmlc.py`.

2. **Diagnostic Pipeline:**
   - Conversion of log messages into machine-readable formats via JSON.

3. **Context-Aware Error Handling:**
   - Track multi-location errors and related auxiliary issues.

4. **Code Integration Features:**
   - Hooks for enhanced compilation workflows.

The following sections outline the major modules and their interactions.

---

## Detailed Components Breakdown

### 1. **AI Diagnostic Subsystem**

#### Architecture of AI Diagnostics

The AI Diagnostics subsystem integrates directly with the existing error-handling frameworks in the DML compiler:

#### Key Modules:
- `ErrorCategory`: Groups errors into 10 strategic categories (e.g., syntax, type mismatch).
- `AIDiagnostic`:
  - Turns raw `LogMessage` instances into structured, detailed diagnostics, with contextual fix recommendations.
  - Example categories mapped with fix paths:
    | **Category**         | **Fix Strategy**                   |
    |----------------------|-----------------------------------|
    | Syntax Errors        | Adjust brackets, validate syntax |
    | Undefined Symbols    | Verify imports/modules linkage   |

---
