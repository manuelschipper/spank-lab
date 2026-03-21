# slap-claude

**Slap your laptop to steer Claude Code's behavior.**

50% slop, 50% an experiment on human and AI physical interactions.

Slap your MacBook and Claude changes personality. Light taps make it go faster. Hard slaps make it stop and apologize. 2 profiles, each with a unique mechanic for translating physical force into AI behavior.

## Profiles

### angry (default)

Standard frustration feedback. More slaps = Claude slows down, asks more, enters gentle-parent mode. At angry level, 30% of tool calls are randomly denied to force a conversation. Yo-yo between frustrated and calm three times and it blows up (blowout — all tool calls denied for 5 minutes).

| Level | Score | Hook | Behavior |
|-------|-------|------|----------|
| calm | < 3.0 | - | Normal operation |
| frustrated | 3.0 - 7.0 | - | Checks assumptions, concise, safe steps |
| hot | 7.0 - 10.0 | - | Slows down, presents options, acknowledges mistakes |
| angry | > 10.0 | 30% `deny` | Full stop. "I can tell this isn't going well." |
| blowout | 3rd cycle | 100% `deny` | Locked out for 5 min. "We need to talk." |

### horse

Your MacBook is a horse. Light taps spur it to go faster. Hard slaps make it buck you off.

Uses **dual amplitude scoring** — events split by force into spur (< 0.25g) and buck (>= 0.25g) channels with independent decay. The hook returns `allow` (speed mode) or `deny` (buck mode) to mechanically override permissions.

| State | Trigger | Hook |
|-------|---------|------|
| normal | no taps | normal permissions |
| speed | light taps (spur >= 2.5) | `allow` all — full autonomy |
| buck | hard slaps (buck >= 3.0) | `deny` all — blocked until calm |

## Quick Setup

```bash
# 1. Clone and build
git clone --recursive https://github.com/manuelschipper/slap-claude.git
cd slap-claude
make

# 2. Start the slap detector (needs sudo for accelerometer)
# Terminal 1:
./slap-claude

# 3. Start the vibe-check daemon (pick a profile)
# Terminal 2:
python3 vibe-check/vibe_check.py                       # angry (default)
SLAP_PROFILE=horse python3 vibe-check/vibe_check.py    # speed/buck

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
          "command": "python3 /path/to/slap-claude/vibe-check/vibe_check.py --hook"
        }]
      }
    ]
  }
}
```

## Architecture

```
  You slap laptop       accelerometer (IOKit HID)    JSON events
  +-----------+     +-------------------------+     +------------------------+
  |  MacBook  | --> |  spank (Go, --stdio)    | --> | /tmp/slap-events.jsonl |
  +-----------+     +-------------------------+     +------------------------+
                                                             |
                                                             v
                    +------------------------+     +------------------------+
                    | /tmp/slap-vibe-        | <-- |  vibe-check daemon     |
                    |   score.json           |     |  (Python, 500ms loop)  |
                    +------------------------+     +------------------------+
                             |
                             v
                    +------------------------+     +------------------------+
                    |  PreToolUse hook       | --> |  Claude Code           |
                    |  (additionalContext)   |     |  (adjusts behavior)    |
                    +------------------------+     +------------------------+
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SLAP_PROFILE` | `angry` | Profile: angry, horse |
| `SLAP_EVENTS` | `/tmp/slap-events.jsonl` | Path to slap events file |
| `SLAP_SCORE_CACHE` | `/tmp/slap-vibe-score.json` | Path to cached score |

## Credits

Accelerometer reading powered by [taigrr/spank](https://github.com/taigrr/spank) — reads the Apple Silicon IMU via IOKit HID.

## Requirements

- Apple Silicon MacBook (M2 or later)
- `sudo` access (required for IOKit HID accelerometer)
- Go 1.22+ (to build the accelerometer reader)
- Python 3.10+ (for vibe-check)
