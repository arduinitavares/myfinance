# Protect the live financial database

MyFinance creates and verifies a timestamped SQLite backup before changing the live database, and a failed migration must leave the original database usable. Migrations are idempotent and tested against a realistic database copy, restore has a documented command, and destructive database reset is unavailable from the normal application API and remains an explicit development/test-only action.
