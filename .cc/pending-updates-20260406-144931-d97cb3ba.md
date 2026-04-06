# Pending CLAUDE.md Updates

_Generated: 20260406-144931_
_Session: d97cb3ba-a32c-4a10-909e-bfa894af0c1b_

UPDATES_NEEDED

**Added automatic log compression on startup — old JSONL files get gzipped to save disk space.**

Modify the "Key Design Decisions" section to add:

```
- JSONL log format (not markdown) for the source of truth
- Atomic file writes (temp + os.rename) for current.md and state.json
```

Replace with:

```
- JSONL log format (not markdown) for the source of truth
- Atomic file writes (temp + os.rename) for current.md and state.json
- Old JSONL logs (previous days) are automatically gzipped on startup (~85% compression); today's log remains uncompressed for active appending
```
