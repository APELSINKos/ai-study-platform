# AI Study Platform

AI Study Platform is a self-hosted platform for preparing for exams from your own material; its web interface is called Recall. You upload lecture notes or textbook chapters; it answers questions with citations to the exact passage, generates quizzes and flashcards, schedules reviews with spaced repetition and shows which topics need more work.

**Status:** early development. The foundation is in place — API, background worker, database with pgvector, the web client shell, containers and CI. Study features are being added next.

## Tech stack

| Layer | Technology |
| --- | --- |
| Web client | Next.js 16, React 19, TypeScript, Tailwind CSS 4, TanStack Query, next-intl (English and Russian) |
| API and workers | Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Celery |
| Data | PostgreSQL 17 with pgvector, Redis |
| Quality | pytest, ruff, mypy, Vitest, Testing Library, Playwright, GitHub Actions |

## Running locally

```bash
docker compose up --build
```

| Service | URL |
| --- | --- |
| Web client | http://localhost:3000 |
| API documentation | http://localhost:8000/docs |
| Metrics (Prometheus format) | http://localhost:8000/metrics |

The defaults work without any configuration; `.env.example` lists the variables that can be overridden.

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
