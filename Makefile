.PHONY: run install db-init db-migrate db-upgrade db-downgrade db-history

FLASK_APP := app.py
PORT := 5001

# Export so every `flask` invocation below can find the app
export FLASK_APP

# Optional message for `make db-migrate m="add users table"`
m ?= migration

install:
	pip install -r requirements.txt

run:
	FLASK_ENV=development FLASK_DEBUG=1 \
		flask run --host=127.0.0.1 --port=$(PORT)


