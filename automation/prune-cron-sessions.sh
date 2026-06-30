#!/usr/bin/env bash
# prune-cron-sessions.sh — weekly cleanup of old cron sessions from state.db
# Deletes cron sessions older than N days, rebuilds FTS indexes, vacuums.
# Usage: ./prune-cron-sessions.sh [days] (default: 7)
set -euo pipefail

DAYS="${1:-7}"
DB="${HERMES_STATE_DB:-$HOME/state.db}"
CRON_OUTPUT="${HERMES_CRON_OUTPUT:-$HOME/cron/output}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pruning cron sessions older than ${DAYS} days..."

python3 -c "
import sqlite3, os, time

db_path = '${DB}'
days = ${DAYS}
cutoff = time.time() - (days * 86400)

db = sqlite3.connect(db_path)
cur = db.cursor()

# Find old cron sessions
cur.execute('SELECT COUNT(*) FROM sessions WHERE id LIKE ? AND started_at < ?', ('cron_%', cutoff))
old_count = cur.fetchone()[0]

if old_count == 0:
    print(f'  No cron sessions older than {days} days found.')
    db.close()
    exit(0)

# Delete messages from old cron sessions
cur.execute('DELETE FROM messages WHERE session_id IN (SELECT id FROM sessions WHERE id LIKE ? AND started_at < ?)', ('cron_%', cutoff))
msgs_deleted = cur.rowcount

# Delete old cron sessions
cur.execute('DELETE FROM sessions WHERE id LIKE ? AND started_at < ?', ('cron_%', cutoff))
sess_deleted = cur.rowcount

db.commit()

# Rebuild FTS indexes to remove orphaned entries
cur.execute(\"INSERT INTO messages_fts(messages_fts) VALUES('rebuild')\")
cur.execute(\"INSERT INTO messages_fts_trigram(messages_fts_trigram) VALUES('rebuild')\")
db.commit()

before_vacuum = os.path.getsize(db_path)
db.execute('VACUUM')
db.close()
after_vacuum = os.path.getsize(db_path)

reclaimed = (before_vacuum - after_vacuum) / 1024 / 1024
print(f'  Deleted: {sess_deleted} sessions, {msgs_deleted} messages')
print(f'  FTS indexes rebuilt')
print(f'  VACUUM: {before_vacuum/1024/1024:.1f} MB -> {after_vacuum/1024/1024:.1f} MB (reclaimed {reclaimed:.1f} MB)')
"

# Clean old cron output files
if [ -d "$CRON_OUTPUT" ]; then
  find "$CRON_OUTPUT" -name "*.md" -mtime +${DAYS} -delete 2>/dev/null
  echo "  Cleaned cron output files older than ${DAYS} days"
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Done."
