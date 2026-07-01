---
name: nodejs-engineering
description: Engineering standards and best practices for writing Node.js (backend / server / CLI / tooling), TypeScript-first but applies to JS. Apply proactively whenever writing, refactoring, or reviewing Node.js code — HTTP handlers, services, repositories, scripts, modules. Enforces async correctness (async/await, no floating promises, no blocking the event loop), layered architecture with thin controllers and single-responsibility modules, typed boundaries with runtime validation (zod) instead of trusting untyped input, typed error propagation (no swallowed errors / unhandled rejections), validated injected config instead of scattered process.env, and resource cleanup. Triggers on: write a Node service / API / endpoint, add an Express/Fastify/Nest route, write a script, handle async / promises / await, "this file is too big", process.env, error handling, validate a request body, .ts/.js server code, database query, stream a file.
---

# Node.js Engineering Standards

Enforce real backend discipline when writing Node.js. The goal is layered,
type-safe, async-correct services that validate their inputs and fail loudly —
**not** a pile of route handlers with tangled callbacks, `process.env` reads
everywhere, and swallowed errors.

## How to apply this skill

Apply proactively — don't wait to be asked. Whenever you write or refactor
Node.js:

1. Keep the **Core Principles** in mind while writing.
2. Before finishing, run the change through the **Smell checklist**.
3. For deeper patterns (layering, DI, error middleware, streaming, graceful
   shutdown), read `references/patterns.md`.

TypeScript is assumed. In a plain-JS codebase, apply the same discipline via
JSDoc types and runtime validation. Match the project's framework conventions
(Express/Fastify/Nest), but never let that justify fat controllers, floating
promises, or unvalidated input.

---

## Core Principles

### 1. Async correctness — the #1 source of Node bugs

- **`async/await` over callbacks/`.then` chains.** No callback pyramids.
- **No floating promises.** Every promise is `await`ed, returned, or explicitly
  `void`ed with a reason. An unawaited async call swallows errors and races.
- **Run independent work concurrently** with `Promise.all` / `allSettled` — but
  `await` in a loop when calls are genuinely sequential/dependent.
- **Never block the event loop.** No `fs.readFileSync`/`crypto.*Sync` on the hot
  path; offload CPU-heavy work (worker threads, a queue). No unbounded sync loops.

```ts
// ❌ floating promise — rejection is lost, ordering unguaranteed
users.forEach(async (u) => { await sendEmail(u); });

// ❌ needlessly sequential
const a = await fetchA(); const b = await fetchB();   // independent, but serial

// ✅ concurrent, awaited, errors surface
await Promise.all(users.map((u) => sendEmail(u)));
const [a, b] = await Promise.all([fetchA(), fetchB()]);
```

### 2. Layered architecture — thin controllers, single-responsibility modules

Separate transport from logic from data access:

- **Route/controller**: parse & validate input, call a service, shape the
  response. No business logic, no DB calls inline.
- **Service**: business logic, orchestration. Framework-agnostic (no `req`/`res`).
- **Repository/data layer**: persistence. The only place that talks to the DB.

A handler that validates + queries the DB + computes + formats is doing four
jobs — split it. Rough ceiling: modules/functions past ~40 lines or 3 nesting
levels want decomposition (same discipline as the other engineering skills).

### 3. Validate at the boundary — don't trust untyped input

Request bodies, query params, env, external API responses, and message payloads
are `unknown`. Parse them into a typed value **once**, at the edge, with a
runtime validator (zod / valibot). Downstream code then works with real types.

```ts
// ❌ trusting the shape — req.body.amount could be anything
function charge(req: Request) { pay(req.body.userId, req.body.amount); }

// ✅ parse → typed & validated, or reject
const ChargeSchema = z.object({ userId: z.string().uuid(), amount: z.number().positive() });
function charge(req: Request) {
  const { userId, amount } = ChargeSchema.parse(req.body);  // throws → 400 via error handler
  return pay(userId, amount);
}
```

TypeScript types are compile-time only — they do **not** validate runtime input.
`as SomeType` on external data is a lie. Validate.

### 4. Typed errors, propagated — never swallowed

- Define a small operational-error hierarchy (`AppError` → `NotFoundError`,
  `ValidationError`, `ConflictError`) carrying a status code.
- **Distinguish operational errors** (expected: bad input, not found) from
  **programmer errors** (bugs) — handle the former, let the latter crash.
- **Centralize handling** in one error-middleware / handler; don't `try/catch`
  and reshape in every route.
- Never `catch (e) {}` (swallow). Never leave unhandled rejections. Attach
  `process.on('unhandledRejection')` / `uncaughtException` to log & exit.

```ts
// ❌ swallowed — failure vanishes, caller thinks it worked
try { await repo.save(x); } catch (e) {}

// ✅ let it propagate to central handler; add context if useful
await repo.save(x);   // throws AppError subclasses; middleware maps to HTTP status
```

### 5. Config & secrets — validated once, injected

Load and **validate** env at startup into a typed config object; import that
everywhere. No `process.env.FOO` scattered through the code, no `||` defaults
sprinkled around, no secrets hardcoded or committed.

```ts
// config.ts — one validated source of truth
const Env = z.object({ PORT: z.coerce.number().default(3000), DATABASE_URL: z.string().url() });
export const config = Env.parse(process.env);   // fails fast at boot if misconfigured
```

### 6. Security basics are non-negotiable

- **Parameterized queries / query builders / ORM** — never string-concatenate
  SQL or NoSQL filters from user input.
- Never `eval` / `new Function` on input; avoid `child_process` with unsanitized args.
- Validate & bound all input (see #3); set sane body-size limits.
- Don't log secrets/PII. Keep secrets in env/secret manager, never in the repo.

### 7. Manage resources and shutdown

- Use connection **pools**; don't open a client per request. Release/cleanup in
  `finally`.
- **Stream** large payloads/files (`pipeline`) instead of buffering into memory.
- Implement **graceful shutdown**: on `SIGTERM`/`SIGINT`, stop accepting
  connections, drain in-flight work, close DB pools, then exit.

### 8. Structured logging & observability

Use a real logger (pino/winston) with levels and structured fields — not
`console.log` littered everywhere. Include correlation/request IDs. Log at the
boundary, not inside pure logic.

### 9. Idioms & hygiene

- **ESM** (`import`/`export`) for new code; `node:` prefix for builtins.
- Keep pure logic separate from IO so it's testable without mocking the world.
- Prefer the standard lib and small focused deps; audit what you add.
- No top-level side effects in modules meant to be imported.

---

## Smell checklist (run before finishing)

- [ ] Any unawaited/floating promise, or `async` callback passed where its rejection is lost?
- [ ] Any independent awaits run serially that should be `Promise.all`?
- [ ] Any `*Sync` call or heavy CPU work on the request path?
- [ ] Any controller doing business logic or DB access inline (should be service/repo)?
- [ ] Any request body / query / env / external response used without runtime validation?
- [ ] Any `as SomeType` cast standing in for real validation?
- [ ] Any swallowed `catch {}`, or error reshaped ad-hoc instead of via central handler?
- [ ] Any `process.env.X` read outside the validated config module?
- [ ] Any string-built SQL / command from user input?
- [ ] Any large payload buffered instead of streamed; any missing cleanup / graceful shutdown?
- [ ] `console.log` used where structured logging belongs?

If any box is checked, fix it before declaring done.

---

## Decision guides

**"Where does this code go?"** → Touches `req`/`res`? Controller. Business rule?
Service. Talks to the DB/external store? Repository. If one function does more
than one of these, split along those seams.

**"Do I need to validate this?"** → Did the data come from outside this process
(HTTP, env, queue, another service, a file)? Then yes — validate at the
boundary, once.

**"Serial or concurrent?"** → Does await B depend on the result of await A? If
not, `Promise.all` them.

See `references/patterns.md` for extended examples (error middleware, DI &
testable services, streaming with `pipeline`, graceful shutdown, config module).
