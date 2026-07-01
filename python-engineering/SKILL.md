---
name: python-engineering
description: Engineering standards and best practices for writing Python. Apply proactively whenever writing, refactoring, or reviewing Python code — defining functions, classes, modules, data models, or APIs. Enforces modeling the domain with real types (dataclass, Pydantic, TypedDict, Enum) instead of passing bare dicts around, single-responsibility functions with no giant multi-purpose functions, complete type hints (no stray Any), explicit specific error handling, and Pythonic idioms. Triggers on: write Python, add a function or class, define a data model / schema, parse or return data, refactor Python, clean up .py code, "should this be a type", type hints, dataclass, pydantic, TypedDict, "this function is too long".
---

# Python Engineering Standards

Enforce real engineering discipline when writing Python. The goal is code that
models its domain with types, decomposes cleanly, and fails loudly — **not**
`dict`-in / `dict`-out scripts that "work" but can't be reasoned about.

## How to apply this skill

Apply these standards **proactively** — do not wait to be asked. Whenever you
write or refactor Python:

1. Skim the **Core Principles** below and hold them in mind while writing.
2. Before finishing, run the change through the **Smell checklist**.
3. For deeper patterns (protocols, generics, IO separation, error hierarchies),
   read `references/patterns.md`.

Match the surrounding codebase's existing conventions when they conflict with a
stylistic preference here — but never let "matching the code" justify skipping
type modeling or shipping a 200-line function.

---

## Core Principles

### 1. Model the domain with types — not bare dicts

A `dict` flowing through your functions is an untyped, unvalidated,
un-autocompletable bag. The moment data has a **known shape**, give it a type.

Reach for, in rough order of preference:
- `@dataclass(frozen=True)` — plain internal data with behavior/immutability.
- `pydantic.BaseModel` — data crossing a boundary (API, config, external input) that needs validation/parsing.
- `TypedDict` — when you genuinely must stay a `dict` (e.g. JSON interop) but want key/type checking.
- `Enum` — a fixed set of choices. Never magic strings.
- `NamedTuple` — small immutable positional records.

```python
# ❌ dict-driven — no validation, typos are silent, no autocomplete
def create_user(data: dict) -> dict:
    return {"id": new_id(), "name": data["name"], "role": data["role"]}

# ✅ modeled — shape is explicit, validated, and checkable
class Role(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"

@dataclass(frozen=True)
class NewUser:
    name: str
    role: Role

@dataclass(frozen=True)
class User:
    id: UserId
    name: str
    role: Role

def create_user(new: NewUser) -> User:
    return User(id=new_id(), name=new.name, role=new.role)
```

**Rule:** `Dict[str, Any]` (or bare `dict`) in a function signature that crosses
a module/layer boundary is a code smell. Model it.

### 2. One function, one job — no giant functions

A function should do one thing at one level of abstraction. If you're scrolling
to read it, or it has "and" in its honest description, split it.

- Extract cohesive blocks into named helper functions — the name documents intent.
- Use **guard clauses** to flatten nesting instead of `if/else` pyramids.
- Rough ceiling: if a function exceeds ~40 lines or nests deeper than 3 levels, look hard for a seam.

```python
# ❌ one function doing validation + fetch + transform + IO
def sync(order_id): ...  # 80 lines, 4 responsibilities, deep nesting

# ✅ orchestrator delegates to single-purpose helpers
def sync_order(order_id: OrderId) -> SyncResult:
    order = _fetch_order(order_id)
    _validate(order)
    receipt = _build_receipt(order)
    return _persist(receipt)
```

### 3. Type-annotate everything public; ban stray `Any`

Every public function's parameters and return are annotated. `Any` is an
explicit escape hatch, not a default — if you reach for it, justify it or model
the real type. Prefer precise types: `Sequence[T]` over `list` when read-only,
`X | None` over bare `Optional` returns without handling.

```python
# ❌
def totals(rows): ...

# ✅
def totals(rows: Sequence[LineItem]) -> Money: ...
```

### 4. Fail loudly with specific errors — no sentinel returns

Don't signal failure with `None`, `-1`, or `False` that callers forget to check.
Raise a **specific** exception. Define a small domain exception hierarchy.

```python
# ❌ caller has no idea this can "fail", silently propagates None
def find_user(uid) -> dict | None: ...

# ✅ explicit contract; not-found is a real, catchable event
class UserNotFound(LookupError): ...

def get_user(uid: UserId) -> User:
    if (user := _repo.get(uid)) is None:
        raise UserNotFound(uid)
    return user
```

Never `except Exception: pass`. Catch the narrowest exception you can handle,
and let the rest propagate.

### 5. Prefer immutability and purity

- Default to `frozen=True` dataclasses and tuples; mutate only with reason.
- Separate **pure logic** from **IO/side effects** so logic is testable without mocks. Push IO to the edges.
- Never use a mutable default argument (`def f(x=[])`) — the classic shared-state bug. Use `None` + init inside.

### 6. Composition and protocols over deep inheritance

For "interfaces", use `typing.Protocol` (structural typing) rather than abstract
base-class hierarchies or, worse, duck-typed dicts. Favor composing small
objects over tall inheritance trees.

### 7. Be Pythonic

- `pathlib.Path` over `os.path` string juggling.
- f-strings over `%` / `.format`.
- Comprehensions for simple transforms; a real loop when logic is non-trivial (don't nest comprehensions 3 deep).
- Context managers (`with`) for anything with acquire/release.
- `enumerate`/`zip`/`itertools` over manual index bookkeeping.

---

## Smell checklist (run before finishing)

- [ ] Any `dict` / `Dict[str, Any]` crossing a boundary that should be a `dataclass`/`Pydantic`/`TypedDict`?
- [ ] Any magic string/number that should be an `Enum` or named constant?
- [ ] Any function > ~40 lines or > 3 nesting levels that should be split?
- [ ] Any public function missing type annotations, or leaning on `Any`?
- [ ] Any failure signalled by `None`/`False`/`-1` instead of a raised exception?
- [ ] Any `except Exception`/bare `except`, or `except: pass`?
- [ ] Any mutable default argument?
- [ ] Is IO tangled into otherwise-pure logic?

If any box is checked, fix it before declaring done.

---

## Decision guides

**"Should this be a type?"** → If the data has a known set of fields, is passed
between functions, or comes from outside the program: **yes**. A throwaway local
mapping used once, inline: a dict is fine.

**"Should I split this function?"** → If you can name a sub-section with a verb
phrase ("validate the payload", "build the receipt"), that section wants to be
its own function.

See `references/patterns.md` for extended examples (error hierarchies, Protocol
usage, IO/logic separation, generics, parsing-at-the-boundary).
