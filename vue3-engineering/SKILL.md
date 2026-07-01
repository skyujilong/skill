---
name: vue3-engineering
description: Engineering standards and best practices for writing Vue 3 (Composition API + `<script setup>` + TypeScript). Apply proactively whenever writing, refactoring, or reviewing Vue components, composables, or frontend UI. Enforces atomic component decomposition (small single-responsibility SFCs, not 400-line mega-components), extracting logic into composables (useX) instead of stuffing everything into one setup, no giant multi-purpose composables, typed props/emits (defineProps<T>/defineEmits<T>, no any), correct reactivity (ref vs reactive, computed for derived state, no reactivity loss on destructure), minimal state, and one-way data flow (props down, events up, no prop mutation). Triggers on: write a Vue component / SFC, build a UI / page / form, add or refactor a composable, "this component is too big", split a component, .vue files, ref / reactive / computed / watch, defineProps / defineEmits, v-model, "extract this logic", Pinia store.
---

# Vue 3 Engineering Standards

Enforce real component-design discipline for Vue 3. The goal is small,
composable, single-responsibility SFCs with logic pulled into focused
composables — **not** 400-line components with a dozen refs, tangled watchers,
and reactivity that silently breaks.

## How to apply this skill

Apply proactively while writing or refactoring Vue — don't wait to be asked:

1. Keep the **Core Principles** in mind as you build.
2. Before finishing, run the change through the **Smell checklist**.
3. For deeper patterns (composable extraction, reactivity pitfalls, typed
   props/emits/v-model, Pinia), read `references/patterns.md`.

Default to **Composition API + `<script setup lang="ts">`** for new code. Match
the project's existing conventions, but never let that justify a mega-component,
Options-API sprawl, or reactivity bugs from careless destructuring.

---

## Core Principles

### 1. Atomic decomposition — small, single-responsibility SFCs

A component renders one coherent thing. When it juggles multiple concerns or the
template gets long, split it.

- Separate **presentational** (props in → UI out, emits events) from
  **container** (owns state/data-fetching) components.
- Extract a subtree into its own SFC when it's reused, has its own state, is a
  distinct conditional block, or just makes the parent hard to scan.
- Rough ceiling: an SFC past ~150 lines of `<template>`+`<script>`, or with
  deeply nested template markup, usually hides 2–3 components.

### 2. Extract logic into composables — keep `setup` declarative

Stateful/effectful logic (data fetching, subscriptions, form state, derived
computations, event listeners) belongs in a `useX` composable, not inline in
`<script setup>`. The component should read like a description of the UI.

```ts
// ❌ logic tangled into the component
const user = ref<User | null>(null);
const error = ref<Error | null>(null);
onMounted(async () => { /* fetch, retry, cleanup... 25 lines */ });

// ✅ cohesive logic behind a named composable
const { user, error, isLoading } = useUser(id);
```

A composable is a plain function starting with `use`, that may call other
composition APIs and returns reactive state + actions.

### 3. No giant composables — they're single-purpose too

A composable has one responsibility. A `useX` returning 15 things and running
several unrelated watchers is a mega-component in disguise — split into
composable units (`useUser`, `useUserPresence`, `useUserPermissions`) and
compose them. If you can't name it with one noun/verb, it's doing too much.

### 4. Type props and emits precisely — no `any`

Use the type-based `defineProps<T>()` / `defineEmits<T>()`. Model variants with
discriminated unions, not a pile of optional booleans. Type slots when non-trivial.

```ts
// ❌ untyped / loose
const props = defineProps(["variant", "loading"]);

// ✅ typed, with defaults
interface Props { variant: "primary" | "danger"; loading?: boolean }
const props = withDefaults(defineProps<Props>(), { loading: false });
const emit = defineEmits<{ submit: [payload: FormData]; cancel: [] }>();
```

### 5. Correct reactivity — the #1 source of Vue bugs

- **`ref` for primitives / single values; `reactive` for objects** you keep as a
  cohesive unit. Prefer `ref` as the default — it's explicit (`.value`) and
  survives reassignment.
- **Never destructure a `reactive` object or props** — it loses reactivity. Use
  `toRefs` / `toRef`, or access via `props.x` directly.
- **`computed` for derived state — not a `watch` that writes to another ref.**
  Derive, don't sync.
- Don't wrap already-reactive values in more refs; don't `.value` inside templates.

```ts
// ❌ derived state synced by hand via a watcher
const full = ref("");
watch([first, last], () => { full.value = `${first.value} ${last.value}`; });

// ✅ derive
const full = computed(() => `${first.value} ${last.value}`);

// ❌ reactivity lost
const { count } = reactive(state);
// ✅ keep the link
const { count } = toRefs(reactive(state));
```

### 6. Minimize state; derive with `computed`

Store the minimal source of truth; compute the rest with `computed`. Don't mirror
props into local refs (unless intentionally seeding an editable copy — and then
be explicit). Colocate state in the lowest component that needs it.

### 7. `watch`/`watchEffect` only for real side effects

Watchers are for **side effects in response to change** (fetch on id change,
imperative DOM/lib sync, persistence) — not for computing values (that's
`computed`). Prefer `watch` with explicit sources over `watchEffect` when you
want clear dependencies. Clean up listeners/timers in `onUnmounted` (or via the
composable). Reach for `immediate`/`flush` deliberately, not by trial-and-error.

### 8. One-way data flow — props down, events up

- **Never mutate a prop.** Emit an event and let the owner update, or use
  `v-model` / `defineModel` for two-way binding done right.
- Cross-component shared state goes in a **Pinia** store (typed), not a global
  reactive object or deep prop-drilling. Keep stores focused, use getters for
  derived state and actions for mutations.
- Use `provide`/`inject` sparingly for genuinely cross-cutting concerns.

### 9. Conventions & template hygiene

- Components `PascalCase` (multi-word); composables `useCamelCase`; emit names
  `kebab-case` events.
- **Always key `v-for` with a stable id — never the index** for dynamic lists.
- **Never put `v-if` and `v-for` on the same element** — wrap or use a `computed`
  filtered list.
- Keep templates declarative: push non-trivial expressions into `computed`.
- Prefer `<script setup>`; keep `<style scoped>` unless intentionally global.

---

## Smell checklist (run before finishing)

- [ ] Any SFC doing multiple jobs (fetch + filter + render + modal) that should be split?
- [ ] Any component past ~150 lines or with deeply nested template markup?
- [ ] Any stateful/effectful logic inline in `setup` that should be a composable?
- [ ] Any composable returning a huge grab-bag / running unrelated watchers?
- [ ] Any `any` / untyped `defineProps` / untyped `defineEmits`?
- [ ] Any destructuring of `reactive`/props that drops reactivity (needs `toRefs`)?
- [ ] Any `watch` that just derives a value `computed` should produce?
- [ ] Any prop being mutated directly instead of emitting / `v-model`?
- [ ] Any set of optional booleans that should be a discriminated union?
- [ ] Any `v-for` keyed by index, or `v-if` + `v-for` on the same element?
- [ ] Any listener/timer/subscription without cleanup in `onUnmounted`?
- [ ] Shared state passed via deep prop-drilling instead of a Pinia store?

If any box is checked, fix it before declaring done.

---

## Decision guides

**"Should I split this component?"** → If you can name a chunk of the template
("the toolbar", "a user row", "the confirm modal"), or it has its own state,
extract it into an SFC.

**"Should this be a composable?"** → If `setup` contains `ref`/`watch`/lifecycle/
listener logic forming a cohesive, nameable unit (`useUser`, `useDebounced`,
`useForm`), extract it.

**"`computed` or `watch`?"** → Producing a value from other reactive state →
`computed`. Performing a side effect when something changes → `watch`.

See `references/patterns.md` for extended examples (composable extraction,
reactivity pitfalls, typed `v-model`/emits, Pinia store shape).
