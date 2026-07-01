# React Engineering — Extended Patterns

Read this when you need concrete patterns beyond the core `SKILL.md` rules.

## Extracting a custom hook (the standard move)

Any cohesive cluster of `useState` + `useEffect` is a hook waiting to happen.

```tsx
// Before: logic lives in the component, mixed with markup concerns
function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Item[]>([]);
  const [isLoading, setLoading] = useState(false);
  useEffect(() => {
    if (!query) return;
    setLoading(true);
    const ctrl = new AbortController();
    search(query, ctrl.signal)
      .then(setResults)
      .finally(() => setLoading(false));
    return () => ctrl.abort();          // cleanup
  }, [query]);
  return <SearchUI query={query} onQuery={setQuery} results={results} loading={isLoading} />;
}

// After: the hook owns the logic; the component owns the markup
function useSearch(initial = "") {
  const [query, setQuery] = useState(initial);
  const [results, setResults] = useState<Item[]>([]);
  const [isLoading, setLoading] = useState(false);
  useEffect(() => {
    if (!query) return;
    setLoading(true);
    const ctrl = new AbortController();
    search(query, ctrl.signal).then(setResults).finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [query]);
  return { query, setQuery, results, isLoading };
}

function SearchPage() {
  const { query, setQuery, results, isLoading } = useSearch();
  return <SearchUI query={query} onQuery={setQuery} results={results} loading={isLoading} />;
}
```

## Splitting a mega-hook into composable hooks

```tsx
// ❌ one hook does user + presence + permissions + notifications
function useDashboard(userId: string) { /* 120 lines, 6 effects, returns 14 things */ }

// ✅ small hooks, composed where needed
function useUser(id: string): UserState { /* ... */ }
function usePresence(id: string): Presence { /* ... */ }
function usePermissions(user: User | null): Permissions { /* ... */ }

function Dashboard({ userId }: { userId: string }) {
  const { user } = useUser(userId);
  const presence = usePresence(userId);
  const perms = usePermissions(user);
  // compose exactly what this screen needs
}
```

## Compound components over boolean-flag soup

```tsx
// ❌ configuration flags multiply combinatorially
<Card title="X" showFooter footerAlign="right" hasImage imageTop dense />

// ✅ composition — the consumer assembles the parts
<Card>
  <Card.Image src={src} />
  <Card.Body>{children}</Card.Body>
  <Card.Footer align="right"><Button>OK</Button></Card.Footer>
</Card>
```

## Discriminated unions for component variants

```tsx
type AlertProps =
  | { kind: "info"; message: string }
  | { kind: "error"; message: string; onRetry: () => void };

function Alert(props: AlertProps) {
  // TS narrows: onRetry only exists when kind === "error"
  if (props.kind === "error") return <ErrorBanner {...props} />;
  return <InfoBanner message={props.message} />;
}
```

## Derive during render — don't sync state with effects

```tsx
// ❌ two sources of truth kept in sync by hand
const [firstName, setFirst] = useState("");
const [lastName, setLast] = useState("");
const [fullName, setFull] = useState("");
useEffect(() => setFull(`${firstName} ${lastName}`), [firstName, lastName]);

// ✅ one source of truth; the rest is computed
const [firstName, setFirst] = useState("");
const [lastName, setLast] = useState("");
const fullName = `${firstName} ${lastName}`;
```

## "You might not need an effect"

```tsx
// ❌ effect reacting to a click's result
const [submitted, setSubmitted] = useState(false);
useEffect(() => { if (submitted) toast("Saved"); }, [submitted]);
function handleSave() { save(); setSubmitted(true); }

// ✅ do it where the event happens
function handleSave() { save(); toast("Saved"); }
```

## Colocate state at the lowest common owner

Put `useState` in the smallest component that needs it. Lift it up only when a
sibling genuinely needs to read/write the same value. Global/context state is a
last resort for truly cross-cutting concerns (auth, theme, locale), not a
default dumping ground.

## Stable keys for lists

```tsx
// ❌ index key — breaks reordering, insertion, animations
{items.map((it, i) => <Row key={i} item={it} />)}
// ✅ stable identity
{items.map((it) => <Row key={it.id} item={it} />)}
```

## Memoization: measure, don't sprinkle

- `useMemo`/`useCallback` earn their keep when (a) a computation is genuinely
  expensive, or (b) a value/function is passed to a `memo`'d child or a
  dependency array where referential identity matters.
- Wrapping every trivial value adds noise and its own cost. Default to none;
  add when a real re-render problem is observed.

## Error and loading states are first-class

Render explicit `isLoading` / `error` / empty states instead of assuming the
happy path. A data hook should return all of them so the component can branch
declaratively (see `Profile` example in `SKILL.md`).
