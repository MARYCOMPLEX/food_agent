# FAQ and Errors

## Frontend build: `Cannot read file .../frontend/tsconfig.json`

The repository has `frontend/package.json` and Vite config but no `frontend/tsconfig.json`. Add a project/reference config before relying on `npm run build`.

## Frontend runtime receives `undefined` session

The backend wraps new-search data under `data.sessionId`, while `searchStore.ts` reads `res.sessionId`. Normalize the API response at `searchApi.ts` or change the store.

## Progress stays pending

Backend events use `step1` through `step6` and `message`; the frontend uses semantic IDs such as `intent_parsing` and reads `detail`. Align the event DTO once, then test every event type.

## Search results do not recover from PostgreSQL

`schema.py` creates a `search_results` table without `turn_id` and `query`, while `search_results.py` inserts/selects both. Run and verify the migration, or make schema creation idempotently include the current columns.

## History/favorites appear empty

Backend GET responses use `data.items`; frontend stores look for `data.history` and `data.favorites`. The search route also calls nonexistent `create_search_history` instead of the repository's `add_history`.

## SSE reconnect/repeated turn issues

The frontend sends `lastEventIndex` as a query parameter, but backend reads `Last-Event-ID`. Also, a per-session event stream retains prior terminal events while `emitter.reset()` only resets step state. Design a per-turn cursor or reset stream before shipping multi-turn recovery.
