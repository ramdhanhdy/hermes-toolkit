# Deterministic Gates per Task Category
#
# These are post-run checks that verify the deliverable exists and meets
# minimum structural requirements. They do NOT evaluate quality — only
# existence and format. Quality is the judge profile's job.
#
# Usage: bash kanban-gates.sh <task_id> <board> <deliverable_path>
# Exit 0 = pass, exit 1 = fail (with reason printed to stderr)

set -euo pipefail

TASK_ID="${1:-}"
BOARD="${2:-default}"
DELIVERABLE="${3:-}"

if [ -z "$DELIVERABLE" ]; then
  echo "FAIL: no deliverable path provided" >&2
  exit 1
fi

# Gate 1: File/page exists
if [ -f "$DELIVERABLE" ]; then
  echo "PASS: deliverable exists at $DELIVERABLE"
  exit 0
elif [[ "$DELIVERABLE" == notion:* ]]; then
  # Notion page — check via API
  PAGE_ID="${DELIVERABLE#notion:}"
  RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://api.notion.com/v1/pages/$PAGE_ID" \
    -H "Authorization: Bearer ${NOTION_API_KEY:-}" \
    -H "Notion-Version: 2022-06-28")
  if [ "$RESPONSE" = "200" ]; then
    echo "PASS: Notion page exists"
    exit 0
  else
    echo "FAIL: Notion page returned HTTP $RESPONSE" >&2
    exit 1
  fi
else
  echo "FAIL: deliverable not found at $DELIVERABLE" >&2
  exit 1
fi

# Gate 2: No placeholder content (if markdown/text file)
if [ -f "$DELIVERABLE" ]; then
  PLACEHOLDER_COUNT=$(grep -c '\.\.\.' "$DELIVERABLE" 2>/dev/null || echo 0)
  if [ "$PLACEHOLDER_COUNT" -gt 0 ]; then
    echo "WARN: $PLACEHOLDER_COUNT placeholder(s) found in deliverable" >&2
    # Warning, not failure — let the judge decide
  fi
  
  # Gate 3: Minimum content size (100 bytes)
  FILESIZE=$(stat -c%s "$DELIVERABLE" 2>/dev/null || echo 0)
  if [ "$FILESIZE" -lt 100 ]; then
    echo "FAIL: deliverable too small ($FILESIZE bytes)" >&2
    exit 1
  fi
fi

# Gate 4: If code project, check tests run
if [[ "$DELIVERABLE" == */src/* ]] || [[ "$DELIVERABLE" == */tests/* ]]; then
  PROJECT_DIR=$(dirname "$DELIVERABLE")
  if [ -f "$PROJECT_DIR/pytest.ini" ] || [ -d "$PROJECT_DIR/tests" ]; then
    cd "$PROJECT_DIR" && python3 -m pytest --tb=short -q 2>/dev/null
    if [ $? -ne 0 ]; then
      echo "FAIL: tests do not pass" >&2
      exit 1
    fi
  fi
fi

echo "PASS: all deterministic gates passed"
exit 0
