# Device Modeling Language (DML) 1.4 Specification

## Abstract

This document provides a comprehensive specification for the Device Modeling Language (DML) version 1.4, a domain-specific language designed for creating hardware device models for the Simics full-system simulator. DML 1.4 enables developers to model complex hardware devices with register banks, memory-mapped interfaces, and sophisticated behavioral logic while automatically generating the necessary C code and Simics integration.

## Table of Contents

1. [Introduction](#introduction)
2. [Language Overview](#language-overview)
3. [Lexical Structure](#lexical-structure)
4. [Module System](#module-system)
5. [Object Model](#object-model)
6. [Data Types](#data-types)
7. [Parameters](#parameters)
8. [Methods](#methods)
9. [Templates](#templates)
10. [Device Structure](#device-structure)
11. [Standard Library](#standard-library)
12. [Hardware Modeling Patterns](#hardware-modeling-patterns)
13. [Memory Management](#memory-management)
14. [Exception Handling](#exception-handling)
15. [Compilation and Integration](#compilation-and-integration)

## Introduction

Device Modeling Language (DML) 1.4 is a specialized programming language for creating virtual hardware models within the Simics simulation environment. Unlike general-purpose programming languages, DML is specifically designed to:

- Model hardware devices with registers, banks, and memory-mapped interfaces
- Automatically generate Simics configuration classes and interfaces
- Provide built-in support for device state management and checkpointing
- Enable sophisticated hardware behavior modeling through templates and methods

### Key Features

- **Object-Oriented Structure**: Hierarchical device modeling with banks, registers, fields, and connections
- **Template System**: Reusable code patterns for common hardware behaviors
- **Automatic C Code Generation**: Compiles to optimized C code for integration with Simics
- **Built-in Hardware Abstractions**: Native support for registers, memory mapping, and device interfaces
- **Type Safety**: Static type checking with hardware-specific data types
- **Metaprogramming**: Compile-time code generation through parameters and templates

### Target Audience

This specification is intended for:
- Hardware engineers developing device models
- Software developers creating Simics-based simulators
- System architects designing virtual platforms
- Researchers working with full-system simulation

## Language Overview

DML 1.4 combines imperative programming constructs similar to C with declarative hardware modeling features. The language is structured around an object model where devices contain hierarchical structures of banks, registers, and fields.

### Basic Structure

```dml
dml 1.4;
device my_device;

bank control_regs {
    register status size 4 @ 0x00 {
        field ready @ [0];
        field error @ [1];
    }

    register config size 4 @ 0x04 is (read, write) {
        method write(uint64 value) {
            if (value & 0x80000000) {
                log info: "Device enabled";
            }
            default(value);
        }
    }
}
```

### Programming Paradigms

DML 1.4 supports multiple programming paradigms:

1. **Declarative Hardware Description**: Object declarations define device structure
2. **Imperative Programming**: Method bodies use C-like syntax for behavior
3. **Template-Based Programming**: Reusable patterns through template instantiation
4. **Metaprogramming**: Compile-time code generation through parameters

## Lexical Structure

### Character Encoding

DML source files use UTF-8 encoding. Non-ASCII characters are permitted only in:
- Comments
- String literals

Unicode BiDi control characters (U+2066 to U+2069 and U+202a to U+202e) are not allowed.

### Reserved Words

DML reserves all ISO/ANSI C keywords plus additional language-specific keywords:

**C Keywords**: `auto`, `break`, `case`, `char`, `const`, `continue`, `default`, `do`, `double`, `else`, `enum`, `extern`, `float`, `for`, `goto`, `if`, `int`, `long`, `register`, `return`, `short`, `signed`, `sizeof`, `static`, `struct`, `switch`, `typedef`, `union`, `unsigned`, `void`, `volatile`, `while`

**C99/C++ Extensions**: `restrict`, `inline`, `this`, `new`, `delete`, `throw`, `try`, `catch`, `template`

**DML-Specific Keywords**: `after`, `assert`, `call`, `cast`, `defined`, `each`, `error`, `foreach`, `in`, `is`, `local`, `log`, `param`, `saved`, `select`, `session`, `shared`, `sizeoftype`, `typeof`, `undefined`, `vect`, `where`, `async`, `await`, `with`, `stringify`

### Identifiers

Identifiers follow C conventions:
- Begin with letter or underscore
- Followed by letters, numbers, or underscores
- Identifiers beginning with underscore are reserved

### Literals

#### Integer Literals

```dml
// Decimal
123
123_456

// Hexadecimal
0x1a2b
0xeace_f9b6

// Binary
0b1101
0b10_1110
```

Underscores can separate digit groups for readability.

#### String Literals

```dml
"Hello, world!"
"Line 1\nLine 2"
"Quote: \""
"Hex byte: \x1f"
```

Escape sequences:
- `\"` - Double quote
- `\\` - Backslash
- `\n` - Newline
- `\r` - Carriage return
- `\t` - Tab
- `\b` - Backspace
- `\xHH` - Hexadecimal byte value

#### Character Literals

```dml
'a'
'\n'
'\''
```

#### Boolean Literals

```dml
true
false
```

#### Floating-Point Literals

```dml
3.14
2.5e-3
1.0E+10
```

### Comments

```dml
// Single line comment

/* Multi-line
   comment */
```

## Module System

DML employs a simple module system where any source file can be imported. Modules are merged into the main model as if contained in a single file, with some exceptions.

### Import Declaration

```dml
import "filename.dml";
import "./relative/path.dml";
import "../parent/dir/file.dml";
```

### Import Rules

1. Each imported file must be parseable in isolation
2. Imports are idempotent (importing same file twice has no effect)
3. Import hierarchy affects override resolution
4. Files importing a module can override its declarations
5. Relative paths (`./`, `../`) ignore `-I` compiler flags

### Module Scope

Modules may contain:
- Parameter declarations
- Method definitions
- Data fields
- Object declarations
- Global declarations

Modules may NOT contain:
- Device declarations (only in main file)

## Object Model

DML is structured around a hierarchical object model where each device contains member objects, which can contain their own members in a nested fashion.

### Object Hierarchy

```
device
├── bank[]
│   ├── register[]
│   │   └── field[]
│   ├── group[]
│   └── attribute[]
├── port[]
│   └── implement[]
│       └── interface[]
├── connect[]
│   └── interface[]
├── subdevice[]
├── attribute[]
└── event[]
```

### Object Types and Containment Rules

- **device**: Top-level object (exactly one per model)
- **bank**: Register collections (only in device/subdevice)
- **register**: Data storage locations (only in bank)
- **field**: Bit ranges within registers (only in register)
- **port**: Interface groupings (only in device/subdevice)
- **implement**: Interface implementations (only in device/port/bank/subdevice)
- **connect**: Object references (only in device/subdevice/bank/port)
- **interface**: Interface specifications (only in connect)
- **attribute**: Configuration attributes (only in device/bank/port/subdevice/implement)
- **event**: Timed events (anywhere except field/interface/implement/event)
- **group**: Organizational containers (anywhere, neutral containment rules)
- **subdevice**: Sub-systems (only in device/subdevice)

### Object Members

Every object can have:
- **Parameters**: Static configuration values
- **Methods**: Behavioral implementation
- **Session Variables**: Runtime state (not checkpointed)
- **Saved Variables**: Runtime state (automatically checkpointed)

## Data Types

DML builds upon C's type system with hardware-specific extensions.

### Integer Types

#### Standard Integer Types
```dml
int1, int2, ..., int64      // Signed integers
uint1, uint2, ..., uint64   // Unsigned integers

// Aliases
char                        // int8
int                         // int32
```

#### Endian Integer Types
Guaranteed exact byte storage with defined byte order:

```dml
int8_be_t, int8_le_t       // 8-bit big/little endian
int16_be_t, int16_le_t     // 16-bit big/little endian
int24_be_t, int24_le_t     // 24-bit big/little endian
int32_be_t, int32_le_t     // 32-bit big/little endian
int40_be_t, int40_le_t     // 40-bit big/little endian
int48_be_t, int48_le_t     // 48-bit big/little endian
int56_be_t, int56_le_t     // 56-bit big/little endian
int64_be_t, int64_le_t     // 64-bit big/little endian

uint8_be_t, uint8_le_t     // Unsigned variants
// ... (similar pattern for all sizes)
```

Properties:
- Exact byte storage (no padding)
- Natural alignment of 1 byte
- Transparent conversion to/from standard integers

### Floating-Point Types

```dml
double                     // Double-precision floating point
```

### Boolean Type

```dml
bool                       // true or false
```

### Array Types

```dml
int data[100];             // Fixed-size array
char buffer[];             // Variable-size array
```

### Pointer Types

```dml
int *ptr;                  // Pointer to integer
const char *str;           // Pointer to constant string
```

### Structure Types

```dml
typedef struct {
    int x;
    int y;
    char name[16];
} point_t;
```

### Layout Types

Structured data with explicit memory layout control:

```dml
typedef layout "big-endian" {
    uint24 header;
    uint16 length;
    uint32 data;
} packet_layout_t;
```

Features:
- Explicit byte order specification
- Guaranteed memory layout
- Member access returns endian integer types
- Supports integer, endian integer, layout, bitfield, and array members

### Bitfield Types

Named bit ranges within an integer:

```dml
typedef bitfields 32 {
    uint3  type    @ [31:29];
    uint16 payload @ [23:8];
    uint7  flags   @ [7:1];
    uint1  valid   @ [0];
} command_bits_t;
```

Usage:
```dml
local command_bits_t cmd = 0x80001001;
cmd.type = 3;
cmd.valid = 1;
local uint32 raw_value = cmd;
```

### Template Types

Each template defines a corresponding type for object references:

```dml
template custom_register {
    session int access_count;
    shared method increment() {
        access_count++;
    }
}

// Usage
local custom_register reg_ref = cast(my_reg, custom_register);
reg_ref.increment();
```

### Serializable Types

Types that can be automatically checkpointed:
- All primitive types (integers, floating-point, boolean)
- Struct/layout/array types containing only serializable types
- Template types
- Hook reference types

Non-serializable types:
- Pointer types
- `extern` struct types

## Parameters

Parameters are compile-time values that describe static properties. They function similarly to macros but with better scoping and type safety.

### Parameter Declaration

```dml
param name;                        // Untyped parameter
param name: type;                 // Typed parameter (templates only)
param name = value;               // Assignment
param name default value;         // Default value
param name: type = value;         // Combined typed declaration and assignment
param name: type default value;   // Combined typed declaration and default
```

### Parameter Examples

```dml
// Basic parameter
param register_size = 4;

// Default parameter (can be overridden)
param byte_order default "little-endian";

// Typed parameter (in template)
template configurable_register {
    param max_value: uint64;
    param max_value = 0xffffffff;
}
```

### Parameter Override Rules

Parameters can be overridden based on template and import hierarchy:
1. Object instantiating template overrides template declarations
2. Importing file overrides imported file declarations
3. Assignment (`=`) cannot be overridden
4. Must have exactly one dominating declaration

### Typed Parameters

Available only in templates, typed parameters:
- Add template type members
- Require constant, side-effect-free definitions
- Enable access from shared methods
- Cannot contain method calls or device state references

```dml
template bounded_register {
    param min_val: uint64 = 0;
    param max_val: uint64;

    shared method validate(uint64 val) -> (bool) {
        return val >= min_val && val <= max_val;
    }
}
```

### Special Parameters

#### Automatic Parameters
```dml
param parent auto;             // Parent object reference
param qname auto;              // Qualified name string
```

#### Built-in Parameters

Every object has:
- `this`: Reference to current object
- `objtype`: Object type string
- `parent`: Parent object reference (undefined for device)
- `qname`: Qualified name with indices
- `dev`: Device object reference
- `templates`: Template method access

## Methods

Methods provide behavioral implementation for objects. Unlike C functions, methods can have multiple return values and support exception handling.

### Method Declaration

```dml
method name(args...) -> (return_types...) throws {
    // Method body
}
```

Components:
- Input parameters: C-style parameter list
- Return values: Tuple of return types (optional)
- `throws` keyword: Indicates method can throw exceptions (optional)
- Method body: Extended C syntax

### Examples

```dml
// No parameters, no return value
method reset() {
    val = 0;
}

// Parameters with return value
method add(int a, int b) -> (int) {
    return a + b;
}

// Multiple return values
method divide(int a, int b) -> (int, int) {
    return (a / b, a % b);
}

// Exception handling
method safe_divide(int a, int b) -> (int) throws {
    if (b == 0) {
        throw;
    }
    return a / b;
}
```

### Method Types

#### Default Methods
Can be overridden by subtemplate or object:

```dml
method process() default {
    // Default implementation
}
```

#### Shared Methods
Compiled once and shared across template instances:

```dml
template counter {
    session int count;

    shared method increment() {
        count++;
    }

    shared method get_count() -> (int) {
        return count;
    }
}
```

Restrictions on shared methods:
- Can only access template type members
- Cannot access non-template symbols
- Use `this` variable for member access

#### Inline Methods
Deprecated mechanism for constant propagation:

```dml
method calculate(inline int factor) -> (int) {
    return base_value * factor;
}
```

#### Independent Methods
Do not rely on device instance:

```dml
independent method utility_function(int x) -> (int) {
    return x * 2 + 1;
}
```

#### Independent Startup Methods
Called when model loads:

```dml
independent startup method initialize_tables() {
    // Model initialization
}
```

#### Independent Startup Memoized Methods
Results cached across device instances:

```dml
independent startup memoized method compute_lookup_table() -> (int[256]) {
    local int table[256];
    // Expensive computation
    return table;
}
```

### Method Calls

```dml
// Basic call
result = method_name(args...);

// Multiple return values
(a, b) = method_with_multiple_returns();

// Call overridden method
default_result = default(args...);

// Template-qualified call
result = templates.template_name.method_name(args...);
```

### Method References as Function Pointers

```dml
// Get function pointer
local func_ptr = &method_name;

// Independent methods don't include device parameter
independent method helper(int x) -> (int) {
    return x * 2;
}

export helper as "external_helper";
```

## Templates

Templates provide reusable code patterns and define types for object references.

### Template Declaration

```dml
template name {
    // Parameters
    // Methods
    // Variables
    // Sub-objects
}
```

### Template Instantiation

```dml
// During object declaration
register r is (template1, template2);

// Within object body
object_name {
    is template_name;
}
```

### Template as Types

```dml
template register_with_callback {
    session uint64 access_count;

    shared method on_access() {
        access_count++;
    }
}

// Type usage
method process_register(register_with_callback reg) {
    reg.on_access();
    log info: "Register accessed %d times", reg.access_count;
}
```

### Template Inheritance

```dml
template base_register {
    param size = 4;
    method reset() default {
        val = 0;
    }
}

template counted_register is base_register {
    session uint64 reset_count;

    method reset() default {
        reset_count++;
        default(); // Call base implementation
    }
}
```

### Template Override Resolution

Override rules based on hierarchy:
1. Object instantiation overrides template
2. Sub-template overrides parent template
3. Import hierarchy affects precedence
4. Must have one dominating declaration

## Device Structure

### Device Declaration

```dml
dml 1.4;
device device_name;
```

Rules:
- Must be first declaration after language version
- Only one device per main file
- Cannot appear in imported files
- Defines Simics configuration class name

### Banks

Register collections providing memory-mapped interfaces:

```dml
bank register_bank {
    param register_size = 4;        // Default register size
    param byte_order = "little-endian";

    register status @ 0x00;
    register control @ 0x04;
    register data[i < 4] @ 0x10 + i * 4;
}
```

Features:
- Expose registers via `io_memory` interface
- Support register arrays with indexing
- Configurable byte order and default sizes
- Create separate Simics configuration objects

### Registers

Data storage with optional memory mapping:

```dml
register control_reg size 4 @ 0x100 {
    param init_val = 0x80000000;

    method write(uint64 value) {
        if (value & 0x1) {
            // Enable operation
            start_operation();
        }
        default(value);
    }
}

// Unmapped register
register internal_state is (unmapped) {
    param init_val = 0;
}
```

Properties:
- Fixed size (1-8 bytes)
- Optional memory mapping via `offset` parameter
- Automatic checkpointing via attributes
- Value stored in `val` member

### Fields

Bit ranges within registers:

```dml
register status size 4 @ 0x00 {
    field ready    @ [0];
    field error    @ [1];
    field mode     @ [3:2];
    field counter  @ [15:8];
    field reserved @ [31:16];
}
```

Bit numbering:
- Little-endian: LSB = 0, MSB = size*8-1
- Big-endian: MSB = 0, LSB = size*8-1
- Range syntax: `[high:low]` (MSB always first)

### Attributes

Configuration and checkpointing support:

```dml
attribute config_value {
    param type = "i";                // Simics integer type
    param documentation = "Device configuration parameter";

    method get() -> (attr_value_t) {
        return SIM_make_attr_int64(internal_config);
    }

    method set(attr_value_t val) {
        internal_config = SIM_attr_integer(val);
    }
}
```

Standard attribute templates:
- `bool_attr`: Boolean attribute with `val` session variable
- `int64_attr`: 64-bit integer attribute
- `uint64_attr`: 64-bit unsigned integer attribute
- `double_attr`: Double-precision floating-point attribute

### Connects

References to other Simics objects:

```dml
connect target_device {
    param configuration = "required";

    interface signal;
    interface serial_device { param required = false; }
}

method send_signal() {
    if (target_device.obj) {
        target_device.signal.signal_raise();
    }
}
```

### Implements

Interface implementations:

```dml
implement signal {
    method signal_raise() {
        log info: "Signal received";
        // Handle signal
    }

    method signal_lower() {
        log info: "Signal lowered";
        // Handle signal
    }
}
```

### Events

Timed simulation events:

```dml
event timeout is (simple_time_event) {
    method event() {
        log info: "Timeout occurred";
        handle_timeout();
    }
}

method start_timer(double delay_seconds) {
    timeout.post(delay_seconds);
}
```

Event types:
- `simple_time_event`: Time-based, no data
- `simple_cycle_event`: Cycle-based, no data
- `uint64_time_event`: Time-based with uint64 data
- `uint64_cycle_event`: Cycle-based with uint64 data
- `custom_time_event`: Time-based with custom data
- `custom_cycle_event`: Cycle-based with custom data

### Groups

Organizational containers:

```dml
bank control {
    group timer_block[i < 4] {
        register control @ i * 0x20 + 0x00;
        register period  @ i * 0x20 + 0x04;
        register count   @ i * 0x20 + 0x08;
    }
}
```

### Ports

Interface groupings:

```dml
port serial_port[i < 2] {
    implement serial_device {
        method receive_data(uint8 data) {
            buffer[buffer_write_pos] = data;
            buffer_write_pos = (buffer_write_pos + 1) % buffer_size;
        }
    }
}
```

### Subdevices

Device subsystems:

```dml
subdevice dma_controller {
    attribute channel_count {
        param type = "i";
        param init_val = 4;
    }

    bank dma_regs {
        register control @ 0x00;
        register status  @ 0x04;
    }
}
```

## Standard Library

### Universal Templates

Available to all object types:

#### `name`
Provides `name` parameter containing object's user-visible name.

#### `desc`
Provides `desc` parameter for short description and `shown_desc` for user-visible description.

#### `documentation`
Provides `documentation` parameter for detailed description.

#### `init`
Provides abstract `init()` method called during device creation before attribute initialization.

#### `post_init`
Provides abstract `post_init()` method called after attribute initialization.

#### `destroy`
Provides abstract `destroy()` method called during device deletion for cleanup.

#### `object`
Base template for all objects, provides:
- `this`: Current object reference
- `objtype`: Object type string
- `parent`: Parent object reference
- `qname`: Qualified name string
- `dev`: Device object reference
- `templates`: Template method access

### Register Templates

#### Basic Register Behavior

```dml
template read {
    method read_register(uint64 enabled_bytes, void *aux) -> (uint64) throws {
        return this.get();
    }
}

template write {
    method write_register(uint64 value, uint64 enabled_bytes, void *aux) throws {
        this.set(value);
    }
}
```

#### Specialized Register Templates

```dml
template read_only {
    method write_register(uint64 value, uint64 enabled_bytes, void *aux) throws {
        // Ignore writes
    }
}

template write_only {
    method read_register(uint64 enabled_bytes, void *aux) -> (uint64) throws {
        return 0; // Always read as 0
    }
}

template unimpl {
    method read_register(uint64 enabled_bytes, void *aux) -> (uint64) throws {
        log unimpl: "read of unimplemented register %s", qname;
        return 0;
    }

    method write_register(uint64 value, uint64 enabled_bytes, void *aux) throws {
        log unimpl: "write to unimplemented register %s", qname;
    }
}
```

### Attribute Templates

```dml
template bool_attr {
    session bool val;
    param type = "b";

    shared method get() -> (attr_value_t) {
        return SIM_make_attr_boolean(val);
    }

    shared method set(attr_value_t v) {
        val = SIM_attr_boolean(v);
    }
}

template uint64_attr {
    session uint64 val;
    param type = "i";

    shared method get() -> (attr_value_t) {
        return SIM_make_attr_uint64(val);
    }

    shared method set(attr_value_t v) {
        val = SIM_attr_integer(v);
    }
}
```

### Event Templates

```dml
template simple_time_event {
    shared method post(double delay) {
        SIM_event_post_time(dev.obj, _event, delay, NULL);
    }

    shared method cancel() {
        SIM_event_cancel_time(dev.obj, _event, NULL);
    }

    // Abstract method to implement
    shared method event();
}
```

### Bank Templates

```dml
template bank {
    param register_size default undefined;
    param byte_order default "little-endian";

    // Provides io_memory interface implementation
    implement io_memory {
        method operation(generic_transaction_t *trans,
                        physical_address_t offset,
                        physical_address_t size) -> (exception_type_t) {
            // Route to appropriate register
        }
    }
}
```

## Hardware Modeling Patterns

### Register Access Patterns

#### Simple Read/Write Register
```dml
register simple_reg size 4 @ 0x00 is (read, write);
```

#### Register with Side Effects
```dml
register control size 4 @ 0x00 is (read, write) {
    method write(uint64 value) {
        if (value & 0x1) {
            start_engine();
        }
        if (value & 0x2) {
            stop_engine();
        }
        default(value);
    }
}
```

#### Status Register with Clear-on-Read
```dml
register interrupt_status size 4 @ 0x04 is read {
    method read() -> (uint64) {
        local uint64 status = val;
        val = 0;  // Clear on read
        return status;
    }
}
```

#### Register with Field-Specific Behavior
```dml
register config size 4 @ 0x08 {
    field enable  @ [0] is (read, write);
    field mode    @ [2:1] is (read, write);
    field status  @ [4] is read_only;
    field reserved @ [31:5] is read_only;
}
```

### Memory-Mapped Device Pattern

```dml
device uart_controller;

bank uart_regs {
    param register_size = 4;
    param byte_order = "little-endian";

    // Data register
    register data @ 0x00 is (read, write) {
        method write(uint64 value) {
            transmit_byte(value & 0xff);
            default(value);
        }

        method read() -> (uint64) {
            if (rx_fifo_empty()) {
                return 0;
            }
            return receive_byte();
        }
    }

    // Status register
    register status @ 0x04 is read_only {
        field tx_ready @ [0];
        field rx_ready @ [1];
        field error    @ [2];
    }

    // Control register
    register control @ 0x08 is (read, write) {
        field enable   @ [0];
        field int_enable @ [1];
        field baud_rate @ [15:8];
    }
}

// Internal state
session uint8 rx_fifo[256];
session uint32 rx_head, rx_tail;

method rx_fifo_empty() -> (bool) {
    return rx_head == rx_tail;
}
```

### Interrupt Controller Pattern

```dml
device interrupt_controller;

bank regs {
    register pending @ 0x00 is read_only {
        method read() -> (uint64) {
            return interrupt_pending;
        }
    }

    register enable @ 0x04 is (read, write) {
        method write(uint64 value) {
            interrupt_enable = value;
            update_interrupt_output();
            default(value);
        }
    }

    register ack @ 0x08 is write_only {
        method write(uint64 value) {
            interrupt_pending &= ~value;  // Clear acknowledged
            update_interrupt_output();
        }
    }
}

session uint32 interrupt_pending;
session uint32 interrupt_enable;

connect cpu {
    interface signal;
}

method set_interrupt(uint32 irq_num) {
    interrupt_pending |= (1 << irq_num);
    update_interrupt_output();
}

method update_interrupt_output() {
    local bool should_interrupt = (interrupt_pending & interrupt_enable) != 0;
    if (should_interrupt) {
        cpu.signal.signal_raise();
    } else {
        cpu.signal.signal_lower();
    }
}
```

### DMA Controller Pattern

```dml
device dma_controller;

bank control_regs {
    group channel[i < 4] {
        register src_addr @ i * 0x20 + 0x00 is (read, write);
        register dst_addr @ i * 0x20 + 0x04 is (read, write);
        register length   @ i * 0x20 + 0x08 is (read, write);
        register control  @ i * 0x20 + 0x0c is (read, write) {
            field enable @ [0];
            field interrupt_enable @ [1];
            field direction @ [2]; // 0=mem-to-mem, 1=mem-to-dev

            method write(uint64 value) {
                if ((value & 0x1) && !(val & 0x1)) {
                    // Starting DMA transfer
                    start_dma_transfer(i);
                }
                default(value);
            }
        }
        register status @ i * 0x20 + 0x10 is read_only {
            field busy      @ [0];
            field complete  @ [1];
            field error     @ [2];
        }
    }
}

method start_dma_transfer(int channel) {
    local uint64 src = channel.src_addr.val;
    local uint64 dst = channel.dst_addr.val;
    local uint64 len = channel.length.val;

    // Start asynchronous transfer
    dma_transfer_event.post(0.001, channel); // 1ms delay
}

event dma_transfer_event is (uint64_time_event) {
    method event(uint64 channel) {
        // Simulate DMA completion
        channel.status.busy = 0;
        channel.status.complete = 1;

        if (channel.control.interrupt_enable) {
            raise_dma_interrupt(channel);
        }
    }
}
```

### Timer/Counter Pattern

```dml
device timer_device;

bank timer_regs {
    register counter @ 0x00 is read_only {
        method read() -> (uint64) {
            if (running) {
                return current_count();
            }
            return counter_value;
        }
    }

    register period @ 0x04 is (read, write) {
        method write(uint64 value) {
            period_value = value;
            if (running) {
                restart_timer();
            }
            default(value);
        }
    }

    register control @ 0x08 is (read, write) {
        field enable    @ [0];
        field interrupt @ [1];
        field one_shot  @ [2];

        method write(uint64 value) {
            local bool was_running = running;
            running = (value & 0x1) != 0;

            if (running && !was_running) {
                start_timer();
            } else if (!running && was_running) {
                stop_timer();
            }
            default(value);
        }
    }
}

session bool running;
session uint64 counter_value;
session uint64 period_value;
session double start_time;

event timer_tick is (simple_time_event) {
    method event() {
        counter_value++;

        if (counter_value >= period_value) {
            counter_value = 0;

            if (control.interrupt) {
                generate_interrupt();
            }

            if (!control.one_shot) {
                // Restart for continuous mode
                timer_tick.post(period_to_seconds(period_value));
            } else {
                running = false;
                control.enable = 0;
            }
        } else {
            timer_tick.post(period_to_seconds(1));
        }
    }
}

method start_timer() {
    start_time = SIM_time();
    counter_value = 0;
    timer_tick.post(period_to_seconds(1));
}
```

### Network Interface Pattern

```dml
device ethernet_controller;

// Receive buffer management
session uint8 rx_buffer[2048];
session uint32 rx_length;
session bool packet_ready;

// Transmit buffer
session uint8 tx_buffer[2048];
session uint32 tx_length;

bank mac_regs {
    register control @ 0x00 is (read, write) {
        field enable_rx @ [0];
        field enable_tx @ [1];
        field reset     @ [31];

        method write(uint64 value) {
            if (value & 0x80000000) {
                reset_controller();
                return; // Reset clears register
            }
            default(value);
        }
    }

    register mac_addr_low  @ 0x04 is (read, write);
    register mac_addr_high @ 0x08 is (read, write);

    register rx_data @ 0x10 is read {
        method read() -> (uint64) {
            if (!packet_ready) return 0;

            local uint64 data = 0;
            // Read 4 bytes from buffer
            for (local int i = 0; i < 4; i++) {
                if (rx_read_pos < rx_length) {
                    data |= (rx_buffer[rx_read_pos++] << (i * 8));
                }
            }

            if (rx_read_pos >= rx_length) {
                packet_ready = false;
                rx_read_pos = 0;
            }

            return data;
        }
    }

    register tx_data @ 0x14 is write {
        method write(uint64 value) {
            if (tx_length < sizeof(tx_buffer) - 4) {
                for (local int i = 0; i < 4; i++) {
                    tx_buffer[tx_length++] = (value >> (i * 8)) & 0xff;
                }
            }
        }
    }

    register tx_control @ 0x18 is write {
        field transmit @ [0];
        field length   @ [15:8];

        method write(uint64 value) {
            if (value & 0x1) {
                tx_length = (value >> 8) & 0xff;
                transmit_packet();
            }
        }
    }
}

connect network {
    interface ethernet_common;
}

implement ethernet_common {
    method frame(const frags_t *frame, eth_frame_crc_status_t crc_status) {
        if (!control.enable_rx) return;

        if (!packet_ready && frame->len <= sizeof(rx_buffer)) {
            // Copy frame to receive buffer
            local uint32 offset = 0;
            for (local int i = 0; i < frame->frag_count; i++) {
                local uint32 frag_len = frame->frags[i].len;
                memcpy(&rx_buffer[offset], frame->frags[i].data, frag_len);
                offset += frag_len;
            }
            rx_length = offset;
            packet_ready = true;
            rx_read_pos = 0;

            // Generate receive interrupt
            if (interrupt_enable.rx_ready) {
                generate_rx_interrupt();
            }
        }
    }
}

method transmit_packet() {
    if (!control.enable_tx || !network.obj) return;

    // Create frame descriptor
    local frags_t frame;
    frame.frag_count = 1;
    frame.frags[0].data = tx_buffer;
    frame.frags[0].len = tx_length;
    frame.len = tx_length;

    // Transmit via network interface
    network.ethernet_common.frame(&frame, Eth_Frame_CRC_Ok);

    tx_length = 0; // Clear transmit buffer

    if (interrupt_enable.tx_complete) {
        generate_tx_interrupt();
    }
}
```

## Memory Management

DML provides memory management through `new` and `delete` operators similar to C++.

### Dynamic Allocation

```dml
// Allocate single object
local int *ptr = new int;
*ptr = 42;

// Allocate array
local char *buffer = new char[1024];
strcpy(buffer, "Hello, World!");

// Allocate and initialize
local point_t *p = new point_t;
p->x = 10;
p->y = 20;
```

### Deallocation

```dml
// Free single object
delete ptr;

// Free array
delete [] buffer;

// Free struct
delete p;
```

### Memory Management in Templates

```dml
template dynamic_buffer {
    session uint8 *data;
    session uint32 size;
    session uint32 capacity;

    method init() {
        capacity = 1024;
        data = new uint8[capacity];
        size = 0;
    }

    method destroy() {
        delete [] data;
    }

    method resize(uint32 new_capacity) {
        if (new_capacity <= capacity) return;

        local uint8 *new_data = new uint8[new_capacity];
        if (data) {
            memcpy(new_data, data, size);
            delete [] data;
        }
        data = new_data;
        capacity = new_capacity;
    }
}
```

### Best Practices

1. **Always pair `new` with `delete`**
   ```dml
   method process_data() {
       local uint8 *temp = new uint8[256];
       // ... use temp ...
       delete [] temp;
   }
   ```

2. **Use `destroy` template for cleanup**
   ```dml
   template managed_resource is destroy {
       session void *resource;

       method init() {
           resource = allocate_resource();
       }

       method destroy() {
           free_resource(resource);
       }
   }
   ```

3. **Check for allocation failure**
   ```dml
   method allocate_buffer(uint32 size) -> (uint8 *) {
       local uint8 *buffer = new uint8[size];
       if (!buffer) {
           log error: "Memory allocation failed";
           return NULL;
       }
       return buffer;
   }
   ```

## Exception Handling

DML provides basic exception handling through `try`/`throw` mechanism.

### Throwing Exceptions

```dml
method divide(int a, int b) -> (int) throws {
    if (b == 0) {
        log error: "Division by zero";
        throw;
    }
    return a / b;
}

method validate_input(uint64 value) throws {
    if (value > max_allowed_value) {
        throw "Value exceeds maximum";
    }
}
```

### Catching Exceptions

```dml
method safe_operation() {
    try {
        local int result = divide(10, 0);
        log info: "Result: %d", result;
    } catch {
        log error: "Division failed";
        // Handle error
    }
}

method process_with_recovery() {
    local bool success = false;
    try {
        risky_operation();
        success = true;
    } catch {
        log warning: "Operation failed, using default";
        use_default_behavior();
    }
}
```

### Exception Propagation

```dml
method inner_function() throws {
    // This may throw
    validate_state();
}

method middle_function() throws {
    // Exceptions propagate automatically
    inner_function();
}

method outer_function() {
    try {
        middle_function();
    } catch {
        log error: "Error in call chain";
    }
}
```

### Best Practices

1. **Use exceptions for exceptional conditions**
   ```dml
   method read_register_safe() -> (uint64) throws {
       if (!device_ready()) {
           throw "Device not ready for read";
       }
       return read_register_value();
   }
   ```

2. **Document exception behavior**
   ```dml
   // This method throws if the configuration is invalid
   method configure_device(uint32 config) throws {
       if (!is_valid_config(config)) {
           throw;
       }
       apply_configuration(config);
   }
   ```

3. **Clean up resources in exception handlers**
   ```dml
   method complex_operation() {
       local uint8 *buffer = new uint8[1024];
       try {
           process_buffer(buffer);
       } catch {
           delete [] buffer;
           throw; // Re-throw
       }
       delete [] buffer;
   }
   ```

## Compilation and Integration

### Build Process

1. **DML Compilation**
   ```bash
   dmlc -I./lib -I./include device.dml
   ```

2. **Generated Files**
   - `device.c`: Main device implementation
   - `device.h`: Device header file
   - `device_dml.py`: Python integration module

3. **Integration with Simics Module**
   ```make
   DEVICE_CLASSES = my_device
   SRC_FILES = device.c additional_code.c

   include $(SIMICS_BASE)/makefiles/model-makefile
   ```

### Compiler Options

- `-I<dir>`: Add include directory for imports
- `-g`: Generate debug information
- `-O`: Enable optimizations
- `--warn-unused`: Warn about unused declarations
- `--coverity`: Generate Coverity analysis annotations
- `--no-line-marks`: Disable line number generation

### Generated Code Structure

```c
// Device structure
typedef struct {
    conf_object_t obj;
    // Session variables
    uint32 register_values[NUM_REGISTERS];
    // Other device state
} my_device_t;

// Interface implementations
static void my_device_signal_raise(conf_object_t *obj);

// Attribute getters/setters
static attr_value_t get_register_attr(void *dont_care,
                                     conf_object_t *obj,
                                     attr_value_t *idx);

// Initialization function
void init_my_device_class(void);
```

### Integration Best Practices

1. **Module Organization**
   ```
   my_device/
   ├── src/
   │   ├── device.dml
   │   ├── registers.dml
   │   └── interfaces.dml
   ├── include/
   │   └── device_types.h
   ├── test/
   │   └── test_device.py
   └── Makefile
   ```

2. **Modular Design**
   ```dml
   // main.dml
   dml 1.4;
   device my_device;

   import "registers.dml";
   import "interfaces.dml";
   import "interrupts.dml";
   ```

3. **Version Management**
   ```dml
   dml 1.4;
   device my_device;

   param device_version = "1.2.3";
   param api_version = 2;
   ```

## Conclusion

DML 1.4 provides a comprehensive framework for modeling hardware devices in virtual simulation environments. Its combination of declarative device structure, imperative behavioral programming, and template-based code reuse makes it well-suited for creating maintainable and efficient device models.

Key strengths include:
- **Hardware-focused abstractions**: Registers, banks, and fields as first-class objects
- **Template system**: Promotes code reuse and consistent patterns
- **Automatic integration**: Seamless Simics configuration class generation
- **Type safety**: Static typing with hardware-specific types
- **Familiar syntax**: C-like programming model for behavioral code

The language continues to evolve with new features and improvements while maintaining backward compatibility and integration with the broader Simics ecosystem.

---

*This specification covers DML 1.4 as implemented in the Device Modeling Language compiler. For the latest updates and detailed API documentation, refer to the official Simics documentation and DML library files.*