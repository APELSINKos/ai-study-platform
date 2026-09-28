# AI Study Platform

AI Study Platform is a self-hosted platform for preparing for exams from your own material; its web interface is called Recall. You upload lecture notes or textbook chapters; it answers questions with citations to the exact passage, generates quizzes and flashcards, schedules reviews with spaced repetition and shows which topics need more work.

**Status:** early development. Accounts and sign-in work, and the web client shell and dashboard are in place, on top of the API, background worker, database with pgvector, containers and CI. Study features are next.

## Tech stack

| Layer | Technology |
| --- | --- |
| Web client | Next.js 16, React 19, TypeScript, Tailwind CSS 4, TanStack Query, next-intl (English and Russian) |
| API and workers | Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Celery |
| Data | PostgreSQL 17 with pgvector, Redis |
| Quality | pytest, ruff, mypy, Vitest, Testing Library, Playwright, GitHub Actions |

## Running locally

Requires Docker with Compose v2 for the stack, and Node 22 (`npm ci` in `frontend/`) for the frontend checks and `make e2e` (once: `npx playwright install chromium`).

```bash
docker compose up --build
```

| Service | URL |
| --- | --- |
| Web client | http://localhost:3000 |
| API documentation | http://localhost:8000/docs |
| Metrics (Prometheus format) | http://localhost:8000/metrics |

The defaults work without any configuration; `.env.example` lists the variables that can be overridden.

## Authentication

The web client signs in with httpOnly cookies and a double-submit CSRF token. API clients, including Swagger's "Authorize" button, use a bearer token from `POST /api/v1/auth/token` instead. Access tokens are short-lived JWTs; refresh tokens are opaque, stored hashed, and rotated on every use — a token used again after rotation revokes its whole session family. Sign-in and registration are both rate-limited.

## Development

| Command | What it does |
| --- | --- |
| `make up` / `make down` | Start or stop the stack |
| `make test` | Backend tests (with PostgreSQL and Redis) and frontend tests |
| `make lint`, `make typecheck` | ruff, mypy, ESLint, Prettier, TypeScript |
| `make e2e` | Playwright tests against the running stack |
| `make migrate` | Apply database migrations |
| `make api-types` | Regenerate the frontend API types from the backend OpenAPI schema |

## Project structure

```
backend/     FastAPI application, Celery worker, Alembic migrations, tests
frontend/    Next.js application, unit and end-to-end tests
compose.yaml Local stack: PostgreSQL, Redis, migrations, API, worker, web client
```

## License

[MIT](LICENSE)
