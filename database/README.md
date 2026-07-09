# Database

The Windows MVP uses SQLite by default:

```text
backend/data/evident_ai.db
```

SQLAlchemy creates the local SQLite tables automatically when FastAPI starts.

PostgreSQL is not required for the current MVP, but the backend can be moved to
PostgreSQL later by setting `EVIDENT_DATABASE_URL` in `backend/.env` and adding
the appropriate database driver dependency.
