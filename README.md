# spank dat Claude

**Slap your laptop to steer Claude Code's behavior.**

A physical frustration feedback loop for AI coding assistants. Slap your MacBook when Claude does something dumb. The harder and more often you slap, the more cautious it becomes -- asking for confirmation, slowing down, double-checking assumptions.

## Quick Setup

```bash
# 1. Clone with the spank subproject
git clone https://github.com/manuelschipper/spank-dat-claude.git
cd spank-dat-claude
make

# 2. Start the slap detector (needs sudo for accelerometer)
# Terminal 1:
./spank-claude

# 3. Start the vibe-check daemon
# Terminal 2:
python3 vibe-check/vibe_check.py

# 4. Add the PreToolUse hook to ~/.claude/settings.json:
```

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [{
          "type": "command",
          "command": "python3 /absolute/path/to/spank-dat-claude/vibe-check/vibe_check.py --hook"
        }]
      }
    ]
  }
}
```

## Frustration Levels

| Level | Score | Claude's Behavior |
|-------|-------|-------------------|
| **calm** | < 3.0 | Normal autonomous operation |
| **frustrated** | 3.0 -- 7.0 | Double-checks assumptions, concise responses, safe steps |
| **hot** | 7.0 -- 10.0 | Slows down, presents options, acknowledges mistakes |
| **angry** | > 10.0 | Full stop. Asks what went wrong. Baby steps only. |

## Architecture

```
  You slap laptop       accelerometer (IOKit HID)    JSON events
  +-----------+     +-------------------------+     +------------------------+
  |  MacBook  | --> |  spank (Go, --stdio)    | --> | /tmp/spank-events.jsonl|
  +-----------+     +-------------------------+     +------------------------+
                                                             |
                                                             v
                    +------------------------+     +------------------------+
                    | /tmp/spank-vibe-       | <-- |  vibe-check daemon     |
                    |   score.json           |     |  (Python, 500ms loop)  |
                    +------------------------+     +------------------------+
                             |
                             v
                    +------------------------+     +------------------------+
                    |  PreToolUse hook       | --> |  Claude Code           |
                    |  (additionalContext)   |     |  (adjusts behavior)    |
                    +------------------------+     +------------------------+
```

## Components

| Component | Language | Description |
|-----------|----------|-------------|
| **spank** | Go | Fork of taigrr/spank. Reads Apple Silicon accelerometer via IOKit HID, detects slaps, outputs JSON events |
| **vibe-check** | Python | Daemon that scores slap events with exponential decay. PreToolUse hook injects behavioral context into Claude Code via `additionalContext` |
| **spank-claude** | Bash | Launcher script for spank in silent event-only mode |

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `SPANK_EVENTS` | `/tmp/spank-events.jsonl` | Path to the slap events file |
| `SPANK_SCORE_CACHE` | `/tmp/spank-vibe-score.json` | Path to the cached frustration score |

## Credits

Built on top of [taigrr/spank](https://github.com/taigrr/spank) -- the original "slap your MacBook, it yells back" project. We forked it, added `--silent` mode, and wired it into Claude Code's hook system.

## Requirements

- Apple Silicon MacBook (M2 or later)
- `sudo` access (required for IOKit HID accelerometer)
- Go 1.22+ (to build spank)
- Python 3.10+ (for vibe-check)
