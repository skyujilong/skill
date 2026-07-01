# Python Engineering — Extended Patterns

Read this when you need concrete patterns beyond the core `SKILL.md` rules.

## Parse, don't validate (model at the boundary)

Convert untyped external input into a typed value **once**, at the edge. After
that, the rest of the code works with a guaranteed-valid type — no defensive
re-checking.

```python
from pydantic import BaseModel, EmailStr, Field

# Boundary model: validates + parses raw request/config/JSON
class CreateUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    role: Role = Role.MEMBER

def handle(raw: dict) -> User:
    req = CreateUserRequest.model_validate(raw)  # raises on bad input, here
    return create_user(NewUser(name=req.name, role=req.role))  # typed from now on
```

Everything downstream of `handle` receives real types, never a raw `dict`.

## Domain error hierarchy

```python
class AppError(Exception):
    """Base for all expected, catchable domain errors."""

class NotFound(AppError): ...
class Conflict(AppError): ...
class ValidationError(AppError): ...

class UserNotFound(NotFound):
    def __init__(self, uid: UserId) -> None:
        super().__init__(f"user {uid!r} not found")
        self.uid = uid
```

Callers catch `NotFound` / `Conflict` at the layer that can act on them (e.g. a
web handler maps `NotFound` → 404). Unexpected errors propagate and crash loudly.

## Protocols over inheritance (structural interfaces)

```python
from typing import Protocol

class UserRepo(Protocol):
    def get(self, uid: UserId) -> User | None: ...
    def save(self, user: User) -> None: ...

# Any class with matching methods satisfies UserRepo — no explicit subclassing.
# Great for injecting a fake in tests without an ABC or mock framework.
def get_user(uid: UserId, repo: UserRepo) -> User:
    if (u := repo.get(uid)) is None:
        raise UserNotFound(uid)
    return u
```

## Separate pure logic from IO (testable core)

```python
# ❌ logic welded to IO — can't test pricing without a DB and clock
def charge_customer(cid):
    cust = db.fetch(cid)
    price = cust["base"] * (0.9 if datetime.now().weekday() < 5 else 1.0)
    db.write_charge(cid, price)

# ✅ pure decision, IO at the edges
@dataclass(frozen=True)
class Customer:
    base: Money
    is_weekday: bool

def compute_price(c: Customer) -> Money:            # pure — trivial to test
    return c.base * (Decimal("0.9") if c.is_weekday else Decimal("1.0"))

def charge_customer(cid: CustomerId, clock: Clock, repo: Repo) -> None:  # IO shell
    cust = repo.fetch(cid)
    repo.write_charge(cid, compute_price(cust.at(clock.now())))
```

## NewType for identifier safety

Stop passing raw `str`/`int` IDs that get mixed up:

```python
from typing import NewType

UserId = NewType("UserId", str)
OrderId = NewType("OrderId", str)

def ship(order: OrderId) -> None: ...
ship(user_id)  # type checker flags this — can't pass a UserId as an OrderId
```

## Generics for reusable containers

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Page[T]:                 # Python 3.12+ syntax
    items: list[T]
    total: int
    next_cursor: str | None
```

## Guard clauses over nested conditionals

```python
# ❌
def process(order):
    if order is not None:
        if order.is_paid:
            if not order.shipped:
                do_ship(order)

# ✅
def process(order: Order) -> None:
    if order is None or not order.is_paid or order.shipped:
        return
    do_ship(order)
```

## Enums instead of string flags

```python
# ❌ status: str  — "activ" typo passes silently, no exhaustiveness
# ✅
class Status(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"
```

## Constants and configuration

- No magic numbers/strings inline — name them (`MODULE`-level constant or `Enum`).
- Configuration is a typed object (`pydantic.BaseSettings` / a frozen dataclass), loaded once, injected — not `os.environ[...]` scattered across the code.
