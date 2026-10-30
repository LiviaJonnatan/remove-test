# frontend

The rule page: a rule's sections with how many comment passages and letters cite each one, and a panel
with the citing passages for the section you click. React built with Vite, served by nginx on port 3000.
The page calls relative `/api/...` URLs, and nginx (`nginx.conf`) forwards them to api-service.

This is the one container that is not Python, so it has `package.json` and `package-lock.json` (installed
with `npm ci`) in place of `pyproject.toml` and `uv.lock`.

- **Run alone:** `docker compose up -d --build --no-deps frontend` (api-service must be up), then open
  http://localhost:3000
- **Develop:** `npm install && npm run dev` (http://localhost:5173, forwards `/api` to localhost:8000)
- **Tests:** `npm ci && npm test` (Vitest; `fetch` is faked, so no API is needed)

Full description: [README, frontend](../README.md#frontend). Screenshot and request log:
[`docs/evidence/frontend/`](../docs/evidence/frontend/README.md).
