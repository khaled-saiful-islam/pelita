# 003 — Docker and Make

## What it does

`make up` takes a fresh clone to a running application. It creates `.env` if it
is missing, builds both images, starts Postgres and waits for it to actually
accept connections, runs migrations, seeds the admin account, starts the API and
the web server, waits for both to report healthy, and prints the login.

There is no step where you are told to wait, open another terminal, or run a
command "once the database is ready".

## How it works

Three services:

| service | image | role |
|---|---|---|
| `db` | `postgres:16-alpine` | Data. Named volume `pelita-db` survives `make down` |
| `api` | built from `backend/` | FastAPI on 8000 |
| `web` | built from `frontend/` | nginx serving the built SPA and proxying `/api` |

### Ordering is enforced by health, not by sleep

`db` has a `pg_isready` healthcheck. `api` declares
`depends_on: db: condition: service_healthy`, so it does not start until Postgres
answers. `web` waits on `api` the same way, and `make up` passes `--wait` so the
command does not return until every healthcheck is green.

A `sleep 5` would work most of the time, which is worse than not working at all —
it fails on slow machines and in CI, intermittently, months later.

### Migrations and seeding are the entrypoint's job

`backend/docker-entrypoint.sh` runs `alembic upgrade head`, then the seed, then
execs the real command. Putting it here rather than in the Makefile means it also
happens on `docker compose up`, on a container restart, and in any deployment
that uses the image directly — not only when someone types `make`.

### The SSE proxy configuration matters

`frontend/nginx.conf` sets `proxy_buffering off` and hour-long read timeouts on
`/api/`. Without them nginx buffers the whole streamed response and delivers it
in one lump at the end. The chat still works, but token-by-token streaming
silently disappears — the kind of bug that is confusing precisely because
nothing errors.

## Targets

| target | what it does |
|---|---|
| `make up` | Build, start, migrate, seed, wait for health, print the login |
| `make down` | Stop everything, keep the database |
| `make logs` | Follow logs from all services |
| `make ps` | Service status |
| `make migrate` | Apply pending migrations |
| `make migration m="..."` | Autogenerate a migration |
| `make seed` | Re-run the seed. Idempotent |
| `make test` | Backend pytest with coverage, then frontend vitest |
| `make lint` | ruff over the backend, `tsc --noEmit` over the frontend |
| `make dev` | Postgres and API in Docker, Vite with hot reload on the host |
| `make reset` | Destroy the database volume and start clean. Asks first |
| `make shell-api` / `make shell-db` | A shell in the API container, psql in the database |

`make test` and `make lint` run the frontend toolchain inside a `node:22-alpine`
container with a named volume for `node_modules`, so neither target needs Node
installed on the host. Docker is the only prerequisite.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `WEB_PORT` | `8080` | Host port for the web UI |
| `API_PORT` | `8000` | Host port for the API |
| `POSTGRES_PORT` | `5433` | Host port for Postgres. Not 5432, so it does not collide with a local install |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `pelita` | Database credentials |

`DATABASE_URL` is derived from the `POSTGRES_*` values in `docker-compose.yml`,
so there is one source of truth for credentials. Set `DATABASE_URL` directly only
when running the API outside Docker.

The Makefile reads ports and the seeded username from `.env` when it exists, so
the banner cannot print a port you are not actually using.

## How to extend it

- **Another service** (Redis, a worker, an MCP server as its own container): add
  it to `docker-compose.yml` with a healthcheck, and have whatever depends on it
  use `condition: service_healthy`.
- **Another startup step**: add it to `docker-entrypoint.sh` before the `exec`.
- **Production build**: the `web` image is already a static build behind nginx.
  The `api` image installs dev dependencies for `make test`; strip that line for
  a smaller production image.

## Known limits

- **One API worker.** Feature 007 keeps cancellation state in process, so
  `--workers 2` would break the stop button. Lifting this needs a shared store;
  the change is described in that feature's document.
- **`make dev` needs Node on the host.** It runs Vite directly for hot reload.
  `make up`, `make test` and `make lint` do not.
- **No TLS.** Put a reverse proxy in front for anything public.
- **The database volume is local.** `make reset` destroys it and asks first, but
  there is no backup story — that belongs to whoever deploys this.
- **`.env` is created from `.env.example` and never updated afterwards.** Pulling
  a change that adds a variable means adding it to your `.env` by hand. Every
  setting has a default in `config.py`, so a missing one degrades rather than
  crashes.

## Verified

On a fresh volume: all three containers reach healthy, `/api/health` reports the
database connected, `/api/config` returns through the nginx proxy, and SPA
fallback routing serves `index.html` for unknown paths.

## Tests

`backend/tests/test_health.py` — `/api/config` works without a database,
`/api/health` returns 503 when the database is unreachable and 200 when it is
not, and `/api/config` exposes no key, secret or URL.

`backend/tests/test_registries.py` — the provider is built from settings alone,
three different backends resolve from env values only, and the contributor order
leaves the documented gaps free.

`frontend/src/lib/api.test.ts` — `/api` prefixing, error-envelope unwrapping,
non-JSON error bodies, conditional content type, and 204 handling.
