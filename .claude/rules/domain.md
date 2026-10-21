---
paths:
  - "services/*/src/*/domain/**"
  - "libs/py/sb_kernel/**"
---
# Domain layer
- Entities and value objects enforce invariants in their constructors; they do no I/O (A2).
- No process logic here; that belongs in use cases (A3). Frozen dataclasses; `Money`, never float (C3).
- Errors subclass `sb_kernel.errors` (C8).
