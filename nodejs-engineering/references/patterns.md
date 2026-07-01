# Node.js Engineering — Extended Patterns

Read this when you need concrete patterns beyond the core `SKILL.md` rules.

## Layered request flow (thin controller → service → repository)

```ts
// repository.ts — the only place that knows about the DB
export class UserRepo {
  constructor(private readonly db: Pool) {}
  async findById(id: UserId): Promise<User | null> {
    const { rows } = await this.db.query("SELECT * FROM users WHERE id = $1", [id]); // parameterized
    return rows[0] ? toUser(rows[0]) : null;
  }
}

// service.ts — business logic, framework-agnostic, no req/res
export class UserService {
  constructor(private readonly repo: UserRepo) {}
  async get(id: UserId): Promise<User> {
    const user = await this.repo.findById(id);
    if (!user) throw new NotFoundError(`user ${id}`);
    return user;
  }
}

// controller.ts — parse/validate in, shape out; no logic, no DB
router.get("/users/:id", async (req, res, next) => {
  try {
    const id = UserIdSchema.parse(req.params.id);
    res.json(await userService.get(id));
  } catch (e) { next(e); }   // hand off to central error handler
});
```

## Operational error hierarchy + central handler

```ts
export class AppError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}
export class NotFoundError extends AppError { constructor(m: string) { super(m, 404); } }
export class ValidationError extends AppError { constructor(m: string) { super(m, 400); } }
export class ConflictError  extends AppError { constructor(m: string) { super(m, 409); } }

// one place maps errors → HTTP; controllers just `next(err)`
export function errorHandler(err: unknown, _req: Request, res: Response, _next: NextFunction) {
  if (err instanceof ZodError)  return res.status(400).json({ error: err.flatten() });
  if (err instanceof AppError)  return res.status(err.status).json({ error: err.message });
  logger.error({ err }, "unhandled error");         // programmer error → log + 500, don't leak details
  res.status(500).json({ error: "internal error" });
}
```

## Crash on truly unexpected errors

```ts
process.on("unhandledRejection", (reason) => { logger.fatal({ reason }, "unhandledRejection"); process.exit(1); });
process.on("uncaughtException", (err) => { logger.fatal({ err }, "uncaughtException"); process.exit(1); });
```

Programmer errors (bugs) should crash the process (a supervisor restarts it) —
don't try to limp along in a corrupted state.

## Dependency injection for testable services

```ts
// Inject collaborators instead of importing singletons — the service becomes
// trivially testable with fakes, no module mocking.
export function makeUserService(deps: { repo: UserRepo; clock: Clock; mailer: Mailer }) {
  return {
    async deactivate(id: UserId) {
      const user = await deps.repo.findById(id);
      if (!user) throw new NotFoundError(`user ${id}`);
      await deps.repo.save({ ...user, deactivatedAt: deps.clock.now() });
      await deps.mailer.send(user.email, "Account deactivated");
    },
  };
}
```

## Concurrency: batch, don't serialize (and don't stampede)

```ts
// independent → concurrent
const results = await Promise.all(ids.map((id) => repo.findById(id)));

// tolerate partial failure
const settled = await Promise.allSettled(tasks.map(run));
const failures = settled.filter((r) => r.status === "rejected");

// bound concurrency for large fan-out (e.g. p-limit) so you don't open 10k sockets
const limit = pLimit(10);
await Promise.all(urls.map((u) => limit(() => fetch(u))));
```

## Stream large data — don't buffer

```ts
import { pipeline } from "node:stream/promises";
import { createReadStream, createWriteStream } from "node:fs";

// ❌ readFile → whole file in memory
// ✅ constant-memory streaming with backpressure + error propagation
await pipeline(createReadStream(src), gzip(), createWriteStream(dest));
```

## Graceful shutdown

```ts
const server = app.listen(config.PORT);
async function shutdown(signal: string) {
  logger.info({ signal }, "shutting down");
  server.close();                 // stop accepting new connections
  await pool.end();               // drain DB pool
  process.exit(0);
}
process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT",  () => void shutdown("SIGINT"));
```

## Validated config module

```ts
// config.ts — imported everywhere; process.env appears nowhere else
import { z } from "zod";
const Env = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  PORT: z.coerce.number().default(3000),
  DATABASE_URL: z.string().url(),
  JWT_SECRET: z.string().min(32),
});
export const config = Env.parse(process.env);   // fail fast at boot
```

## Separate pure logic from IO

```ts
// ❌ decision welded to IO — needs a DB + clock to test pricing
// ✅ pure function decides; the caller does IO
export function computeDiscount(cart: Cart, now: Date): Money { /* pure, unit-testable */ }
async function checkout(cartId: CartId, repo: Repo, clock: Clock) {
  const cart = await repo.getCart(cartId);
  return repo.saveTotal(cartId, computeDiscount(cart, clock.now()));
}
```
