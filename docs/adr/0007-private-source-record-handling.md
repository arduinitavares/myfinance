# Private source records stay local

Raw Source Records contain account identifiers, balances, and transaction history, so they live only in Git-ignored local storage and are mounted read-only when imported. They are never committed or attached to GitHub issues; support requests and automated tests use metadata plus redacted or synthetic fixtures, while local originals remain the provenance evidence used for verification.
