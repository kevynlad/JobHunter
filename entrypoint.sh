#!/bin/bash
# entrypoint.sh - Fixes Railway volume permissions for SQLite

# If the data directory exists (where the Railway volume is mounted),
# change its ownership to appuser before dropping root privileges.
if [ -d "/app/data" ]; then
    chown -R appuser:appuser /app/data
fi

# Switch to the appuser and replace the shell with the command
exec gosu appuser "$@"
