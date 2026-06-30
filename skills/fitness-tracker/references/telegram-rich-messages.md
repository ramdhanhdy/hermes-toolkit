# Telegram Rich Messages Setup

## Problem
Hermes defaults to `platforms.telegram.extra.rich_messages: false`. This causes:
- Long messages (>4096 chars) to split into multiple Telegram messages
- Markdown degradation: tables → bullet lists, `<details>` stripped, task lists → plain text, math → stripped
- Workout analyses, dashboard reports, and meal summaries break into chunks

## Fix

### 1. Enable in config.yaml

```bash
hermes config set platforms.telegram.extra.rich_messages true
```

### 2. Verify it actually took effect

`hermes config set` can append a duplicate `platforms:` block at the end of
config.yaml instead of updating the existing key. The existing block (earlier
in the file) takes precedence, so the change appears to not work.

Verify with python3 raw read:

```python
with open('<hermes-config-dir>/config.yaml','r') as f:
    content = f.read()
import re
matches = [(m.start(), m.group()) for m in re.finditer(r'rich_messages:\s*\w+', content)]
for pos, val in matches:
    print(f'  pos {pos}: {val}')
```

If you see both `false` and `true`, the `false` entry wins (it's earlier in
the file). Patch the file directly:

```python
with open('<hermes-config-dir>/config.yaml','r') as f:
    content = f.read()
content = content.replace('rich_messages: false', 'rich_messages: true', 1)
with open('<hermes-config-dir>/config.yaml','w') as f:
    f.write(content)
```

### 3. Restart the gateway

```bash
hermes gateway restart
```

Cannot restart from inside the gateway (it kills itself). Run from a separate
shell or ask the user to run `/restart` in Telegram.

## How it works

With `rich_messages: true`, Hermes uses Telegram Bot API 10.1's `sendRichMessage`
which accepts up to **32,768 chars** in a single message with full markdown
rendering: tables, collapsible sections, footnotes, task lists, math formulas.

Content above 32,768 chars falls back to the legacy chunking path.

## Trade-off

Rich messages can be harder to copy as plain text on some Telegram clients. For
users who explicitly want long-form markdown (tables, collapsible sections, etc.),
this trade-off is correct. For users who mainly copy code snippets, leave it off.
