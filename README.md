# spank dat Claude

**Slap your laptop to steer Claude Code's behavior.**

50% shitposting, 50% an experiment in Claude-human physical interaction modes.

Slap your MacBook and Claude changes personality. Light taps make it go faster. Hard slaps make it stop and apologize. Get it drunk. Make it roast your code. 4 profiles, each with a unique mechanic for translating physical force into AI behavior.

## Profiles

### angry (default)

Standard frustration feedback. More slaps = Claude slows down, asks more, enters gentle-parent mode. Yo-yo between frustrated and calm three times and it blows up (blowout — all tool calls denied until you talk it through).

| Level | Score | Behavior |
|-------|-------|----------|
| calm | < 3.0 | Normal operation |
| frustrated | 3.0 - 7.0 | Checks assumptions, concise, safe steps |
| hot | 7.0 - 10.0 | Slows down, presents options, acknowledges mistakes |
| angry | > 10.0 | Full stop. "I can tell this isn't going well." |

### horse

Your MacBook is a horse. Light taps spur it to go faster. Hard slaps make it buck you off.

Uses **dual amplitude scoring** — events split by force into spur (< 0.25g) and buck (>= 0.25g) channels with independent decay. The hook returns `allow` (speed mode) or `deny` (buck mode) to mechanically override permissions.

| State | Trigger | Hook |
|-------|---------|------|
| normal | no taps | normal permissions |
| speed | light taps (spur >= 2.5) | `allow` all — full autonomy |
| buck | hard slaps (buck >= 3.0) | `deny` all — blocked until calm |

### drunk

Progressive intoxication with a lifecycle. Getting drunk is easy. The hangover is the price.

Slow decay (120s half-life) means getting drunk is a commitment. When score decays from above hammered, you enter **hangover** instead of sobering up normally. More slaps during hangover make it worse, not re-drunk. Must wait it out.

| Level | Score | Behavior |
|-------|-------|----------|
| sober | < 2.0 | Normal Claude |
| buzzed | 2.0 - 4.5 | Casual tone. `// this is more complex than it needs to be tbh` |
| tipsy | 4.5 - 8.0 | `thingyList`, `doTheNeedful()`. Tangents. Second-guessing. |
| hammered | 8.0 - 13.0 | `bigBoy`, `pleaseWork`, `temp2_final_v3_REAL`. `# TODO: understand what i wrote here when sober` |
| blackout | > 13.0 | `frank` (no explanation). `# future me: i'm sorry`. 30% of tool calls randomly denied. |
| hangover | decaying from hammered+ | `ugh can we do this later.` `# fix this when head stops pounding` |

### roast

Claude progressively roasts your code. Simple spectrum — fast 30s decay so it reads the room.

| Level | Score | Style |
|-------|-------|-------|
| room temp | < 2.0 | Normal. No roast. |
| mild salsa | 2.0 - 5.0 | "I see you named this `data`. Revolutionary." |
| ghost pepper | 5.0 - 9.0 | `# fixing the variable from 'x' to something a human might recognize` |
| surface of the sun | 9.0 - 14.0 | "And here we see the wild nested ternary, desperately trying to express a simple boolean." |
| heat death | > 14.0 | `# here lies processData(). It tried its best. Its best was not enough.` |

Rules: roasts must be specific to real code. Generic insults banned. Roast the code, not the person. Claude's own code must be impeccable.

## Quick Setup

```bash
# 1. Clone and build
git clone --recursive https://github.com/manuelschipper/spank-dat-claude.git
cd spank-dat-claude
make

# 2. Start the slap detector (needs sudo for accelerometer)
# Terminal 1:
./spank-claude

# 3. Start the vibe-check daemon (pick a profile)
# Terminal 2:
SPANK_PROFILE=angry python3 vibe-check/vibe_check.py    # default
SPANK_PROFILE=horse python3 vibe-check/vibe_check.py    # speed/buck
SPANK_PROFILE=drunk python3 vibe-check/vibe_check.py    # intoxication
SPANK_PROFILE=roast python3 vibe-check/vibe_check.py    # code roasts

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
          "command": "SPANK_PROFILE=angry python3 /path/to/spank-dat-claude/vibe-check/vibe_check.py --hook"
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

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SPANK_PROFILE` | `angry` | Profile: angry, horse, drunk, roast |
| `SPANK_EVENTS` | `/tmp/spank-events.jsonl` | Path to slap events file |
| `SPANK_SCORE_CACHE` | `/tmp/spank-vibe-score.json` | Path to cached score |

## Credits

Built on top of [taigrr/spank](https://github.com/taigrr/spank) -- the original "slap your MacBook, it yells back" project. We forked it, added `--silent` mode, and wired it into Claude Code's hook system.

## Requirements

- Apple Silicon MacBook (M2 or later)
- `sudo` access (required for IOKit HID accelerometer)
- Go 1.22+ (to build spank)
- Python 3.10+ (for vibe-check)
