# Development Guide

Local development instructions for the WikiEval backend.

## Prerequisites

- Python 3 with a virtual environment (`venv/` is used in this repo)
- A configured `config.yaml` (see `config.yaml.bak` for the expected keys).
  For local dev make sure it contains `ENV: dev` so CORS and debug mode are
  enabled.

## Setup

Activate the virtualenv and install dependencies:

```bash
source venv/bin/activate
make install
```

`make install` runs `pip install -r requirements.txt`.

## Running the app

```bash
make run
```

This starts Flask in development mode (`FLASK_ENV=development`, `FLASK_DEBUG=1`)
on `http://127.0.0.1:5001` with auto-reload and the debugger enabled.

## Database migrations

Migrations are managed with Flask-Migrate. All targets read `FLASK_APP=app.py`,
which the Makefile exports automatically.

| Command | Description |
|---------|-------------|
| `make db-init` | Initialize the `migrations/` directory. **Run once**, before the first migration. |
| `make db-migrate m="message"` | Autogenerate a migration from model changes. |
| `make db-upgrade` | Apply pending migrations to the database. |
| `make db-downgrade` | Roll back the most recent migration. |
| `make db-history` | Show the migration history. |

### First-time setup

```bash
make db-init
make db-migrate m="add users and contest_requests tables"
make db-upgrade
```

### After changing a model

Whenever you edit `model.py` (e.g. add a column or a table), generate and apply
a new migration:

```bash
make db-migrate m="describe your change"
make db-upgrade
```

> The `m` argument is optional and defaults to `migration`, but always pass a
> descriptive message so the migration history stays readable.
