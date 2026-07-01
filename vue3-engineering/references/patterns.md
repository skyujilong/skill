# Vue 3 Engineering — Extended Patterns

Read this when you need concrete patterns beyond the core `SKILL.md` rules.
All examples assume `<script setup lang="ts">`.

## Extracting a composable (the standard move)

Any cohesive cluster of `ref` + lifecycle + watch is a composable waiting to happen.

```ts
// composables/useUser.ts
import { ref, watch, type Ref } from "vue";

export function useUser(id: Ref<string>) {
  const user = ref<User | null>(null);
  const error = ref<Error | null>(null);
  const isLoading = ref(false);

  watch(id, async (value) => {
    isLoading.value = true;
    error.value = null;
    try {
      user.value = await fetchUser(value);
    } catch (e) {
      error.value = e as Error;
    } finally {
      isLoading.value = false;
    }
  }, { immediate: true });

  return { user, error, isLoading };   // reactive state out
}
```

```vue
<!-- component stays declarative -->
<script setup lang="ts">
const props = defineProps<{ id: string }>();
const { user, error, isLoading } = useUser(toRef(props, "id"));
</script>
```

## Splitting a mega-composable

```ts
// ❌ one composable: user + presence + permissions + notifications (returns 14 things)
// ✅ small, focused, composed at the call site
const { user } = useUser(id);
const presence = usePresence(id);
const perms = usePermissions(user);
```

## Reactivity pitfalls (memorize these)

```ts
// 1. Destructuring reactive drops reactivity
const state = reactive({ count: 0 });
const { count } = state;            // ❌ plain number, won't update
const { count } = toRefs(state);    // ✅ ref, stays linked

// 2. Destructuring props drops reactivity
const props = defineProps<{ id: string }>();
const { id } = props;               // ❌ (before 3.5 reactive-props-destructure)
const id = toRef(props, "id");      // ✅ portable, reactive
watch(() => props.id, onIdChange);  // ✅ or watch a getter

// 3. Reassigning a reactive breaks it
let state = reactive({ n: 0 });
state = reactive({ n: 1 });         // ❌ old references now stale — prefer ref for reassignable values

// 4. Derive with computed, not watch-to-ref
const doubled = computed(() => count.value * 2);   // ✅
```

## Typed props with defaults, and typed emits

```ts
interface Props {
  items: Item[];
  variant?: "list" | "grid";
}
const props = withDefaults(defineProps<Props>(), { variant: "list" });

const emit = defineEmits<{
  select: [id: string];
  update: [item: Item];
  close: [];
}>();

function onRowClick(item: Item) {
  emit("select", item.id);   // type-checked payload
}
```

## Two-way binding done right: `defineModel`

```ts
// child: no prop mutation, no manual update:modelValue plumbing
const model = defineModel<string>();           // Vue 3.4+
// parent: <SearchBox v-model="query" />
```

Pre-3.4 pattern: `props.modelValue` + `emit('update:modelValue', next)` — never
mutate `modelValue` directly.

## Discriminated union props for variants

```ts
type AlertProps =
  | { kind: "info"; message: string }
  | { kind: "error"; message: string; onRetry: () => void };
const props = defineProps<AlertProps>();
// template can branch on props.kind with narrowing
```

## Derive during render — don't sync with watchers

```ts
// ❌ two sources of truth kept in sync by hand
const first = ref(""), last = ref(""), full = ref("");
watch([first, last], () => { full.value = `${first.value} ${last.value}`; });

// ✅ one source of truth; the rest computed
const full = computed(() => `${first.value} ${last.value}`);
```

## `watch` for side effects, with cleanup

```ts
watch(roomId, (id, _prev, onCleanup) => {
  const socket = openSocket(id);
  onCleanup(() => socket.close());   // runs before next call & on unmount
}, { immediate: true });
```

## Pinia store shape (typed, focused)

```ts
export const useCartStore = defineStore("cart", () => {
  const items = ref<CartItem[]>([]);
  const total = computed(() => items.value.reduce((s, i) => s + i.price, 0)); // getter = computed
  function add(item: CartItem) { items.value.push(item); }                    // action = mutation
  return { items, total, add };
});
```

Keep stores single-domain; derived values are `computed` getters; mutations go
through actions. Don't reach into another store's internals — call its actions.

## Template hygiene

```vue
<!-- ❌ v-if + v-for on the same element (ambiguous precedence, re-evaluates per item) -->
<li v-for="u in users" v-if="u.active" :key="u.id">{{ u.name }}</li>

<!-- ✅ filter with a computed, then v-for -->
<li v-for="u in activeUsers" :key="u.id">{{ u.name }}</li>
<!-- const activeUsers = computed(() => users.value.filter(u => u.active)) -->

<!-- ❌ index key on a dynamic list  →  ✅ stable id key -->
```
