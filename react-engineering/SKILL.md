---
name: react-engineering
description: Engineering standards and best practices for writing React (and React + TypeScript). Apply proactively whenever writing, refactoring, or reviewing React components, hooks, or frontend UI. Enforces atomic component decomposition (small single-responsibility components, not 300-line mega-components), extracting logic into custom hooks instead of stuffing everything into one component, no giant multi-purpose hooks, typed props (interfaces, discriminated unions, no any), minimal derived state, and the Rules of Hooks. Triggers on: write a React component, build a UI / page / form, add or refactor a hook, "this component is too big", split a component, custom hook, .tsx/.jsx files, useState / useEffect / useMemo, "extract this logic", frontend component design.
---

# React Engineering Standards

Enforce real component-design discipline. The goal is small, composable,
single-responsibility components with logic pulled into focused custom hooks —
**not** 300-line components with a dozen `useState`s and tangled `useEffect`s.

## How to apply this skill

Apply proactively while writing or refactoring React — don't wait to be asked:

1. Keep the **Core Principles** in mind as you build.
2. Before finishing, run the change through the **Smell checklist**.
3. For deeper patterns (compound components, state colocation, effect
   avoidance, typed variants), read `references/patterns.md`.

Match the existing codebase's conventions on styling/router/data-fetching, but
never let that justify a mega-component or logic that should be a custom hook.

---

## Core Principles

### 1. Atomic decomposition — small, single-responsibility components

A component renders one coherent thing. When it starts juggling multiple
concerns or its JSX gets long, split it.

- Separate **presentational** (dumb, props-in → UI-out) from **container**
  (owns state/data) responsibilities.
- Extract a subtree into its own component when it: is reused, has its own
  state, is conditionally rendered as a block, or simply makes the parent hard to scan.
- Rough ceiling: a component past ~150 lines, or with deeply nested JSX, almost
  always contains 2–3 components trying to escape.

```tsx
// ❌ one component: fetching + filtering + row rendering + modal + pagination
function UserDashboard() { /* 300 lines, 9 useState, 4 useEffect */ }

// ✅ decomposed — each piece has one job
function UserDashboard() {
  const { users, isLoading } = useUsers();      // data logic → hook
  return (
    <Panel>
      <UserToolbar />
      {isLoading ? <Spinner /> : <UserTable users={users} />}
      <Pagination />
    </Panel>
  );
}
```

### 2. Extract logic into custom hooks — components stay declarative

Stateful/effectful logic (data fetching, subscriptions, form state, derived
computations) belongs in a `useX` hook, not inline in the component body. The
component should read like a description of the UI.

```tsx
// ❌ logic tangled into the component
function Profile({ id }: { id: string }) {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => { /* fetch, set, cleanup, retry... 25 lines */ }, [id]);
  // ...more effects, more state...
}

// ✅ cohesive logic behind a named hook
function Profile({ id }: { id: string }) {
  const { user, error, isLoading } = useUser(id);
  if (isLoading) return <Spinner />;
  if (error) return <ErrorState error={error} />;
  return <ProfileCard user={user} />;
}
```

### 3. No giant hooks — hooks are single-purpose too

A custom hook has one responsibility. A `useX` returning 15 values and running 6
effects is a mega-component in disguise — split it into composable hooks
(`useUser`, `useUserPresence`, `useUserPermissions`) and compose them.

The same size discipline as components applies: if a hook is hard to name with a
single noun/verb, it's doing too much.

### 4. Type props precisely — no `any`

- Every component has a typed props interface/type. No implicit `any`.
- Model variants with **discriminated unions**, not a soup of optional booleans.
- Type event handlers and children explicitly.

```tsx
// ❌ ambiguous — illegal combinations are representable
type Props = { primary?: boolean; danger?: boolean; loading?: boolean };

// ✅ discriminated — only valid states exist
type ButtonProps =
  | { variant: "primary"; onClick: () => void }
  | { variant: "danger"; onConfirm: () => void };
```

### 5. Minimize and derive state — don't duplicate

- Store the **minimal** source of truth; **derive** everything else during render (a plain `const`, not another `useState` + `useEffect`).
- Colocate state in the lowest component that needs it; lift only when genuinely shared.
- Don't mirror props into state.

```tsx
// ❌ derived value duplicated into state and synced via effect
const [items, setItems] = useState(all);
const [count, setCount] = useState(0);
useEffect(() => setCount(items.length), [items]);

// ✅ derive during render
const [items, setItems] = useState(all);
const count = items.length;
```

### 6. Use effects only for real synchronization

`useEffect` is for syncing with **external systems** (network, subscriptions,
the DOM, timers) — not for reacting to state you could compute, and not for
logic that belongs in an event handler.

- Transforming data for render → compute it inline (see #5).
- Responding to a user action → do it in the event handler, not an effect watching the result.
- Every effect that subscribes/opens something returns a **cleanup**.
- Dependency arrays are complete and honest (don't silence the linter).

### 7. Composition over prop-drilling and configuration flags

- Pass `children` / render props / compound components instead of threading
  props through many layers or piling boolean config onto one component.
- Reach for Context sparingly, for genuinely cross-cutting state (theme, auth) —
  not as a substitute for good component structure.

### 8. Conventions

- Components `PascalCase`; hooks `useCamelCase`; event handlers `handleX`, handler props `onX`.
- Stable, meaningful list `key`s — never the array index for dynamic lists.
- Keep render pure: no mutation, no side effects during render.
- Memoize (`useMemo`/`useCallback`/`memo`) to fix a **measured** problem or preserve referential identity that matters — not reflexively on everything.

---

## Smell checklist (run before finishing)

- [ ] Any component doing multiple jobs (fetch + filter + render + modal) that should be split?
- [ ] Any component past ~150 lines or with deeply nested JSX?
- [ ] Any stateful/effectful logic inline that should be a custom hook?
- [ ] Any custom hook returning a huge grab-bag / running many unrelated effects?
- [ ] Any `any` / untyped props / untyped event handlers?
- [ ] Any set of optional booleans that should be a discriminated union?
- [ ] Any `useState` + `useEffect` that just derives a value computable during render?
- [ ] Any `useEffect` that's really an event-handler action, or missing cleanup, or with a suppressed dep array?
- [ ] Any array-index `key` on a dynamic list?
- [ ] Any deep prop-drilling that composition/children would solve?

If any box is checked, fix it before declaring done.

---

## Decision guides

**"Should I split this component?"** → If you can describe a chunk of the JSX
with its own name ("the toolbar", "a user row", "the confiral modal"), or it has
its own state, extract it.

**"Should this be a custom hook?"** → If the component body contains `useState`/
`useEffect`/subscription logic that forms a cohesive unit you could name
(`useUser`, `useDebouncedValue`, `useFormState`), extract it.

**"Do I need this effect?"** → If it doesn't touch an external system, you almost
certainly don't. Compute during render or handle in the event.

See `references/patterns.md` for extended examples (compound components, custom
hook extraction, state colocation, effect avoidance, typed variants).
