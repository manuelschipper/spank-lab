# spank dat Claude — Profile Design

4 profiles, each with a unique mechanical identity. Select with `SPANK_PROFILE=<name>`.

## Overview

| Profile | Mechanic | Hook Override | Decay |
|---------|----------|--------------|-------|
| angry | Suppression counter + blowout | deny (blowout) | 45s |
| horse | Dual amplitude scores (spur/buck) | allow (speed) + deny (buck) | 10s both |
| drunk | Lifecycle + hangover ratchet | deny 30% (blackout) | 120s |
| roast | Simple spectrum | - | 30s |

## Backlog (not yet implemented)

- brutally honest — peak amplitude only, no-compliments flag
- paranoid — per-tool fear memory
- stubborn — conviction with backfire
- cheerful — mania + crash

---

## angry (default)

Slaps = "you're doing it wrong."

**Mechanic:** Standard score-based spectrum with **suppression counter**. Every time you go from frustrated back to calm, the counter increments. Third re-entry to frustrated = **blowout** — jumps to angry, locked for 5 minutes, all tool calls denied.

| Level | Score | Hook | Behavior |
|-------|-------|------|----------|
| calm | < 3.0 | - | Normal operation |
| frustrated | 3.0 - 7.0 | - | Re-reads what you asked. Under 15 lines. No preamble. |
| hot | 7.0 - 10.0 | - | Changes approach. One action per turn. "Is this what you want?" |
| angry | > 10.0 | - | Full stop. "I can tell this isn't going well." |
| blowout | 3rd re-entry | `deny` | Locked out. Can talk but can't act. |

**Decay:** 45s half-life.

---

## horse

Your MacBook is a horse. Light taps = spur. Hard slaps = buck.

**Mechanic:** Events split by amplitude into two independent scores:
- **Spur** (amplitude < 0.25g) → 10s half-life
- **Buck** (amplitude >= 0.25g) → 10s half-life, capped at 4.0

Buck always overrides spur. Buck has 3s cooldown after score drops.

| State | Trigger | Hook | Behavior |
|-------|---------|------|----------|
| normal | default | - | Normal operation |
| speed | spur >= 2.5 | `allow` | Full autonomy. Don't ask, just do. |
| buck | buck >= 3.0 | `deny` | Blocked. "The horse remembers." |

---

## drunk

Progressive intoxication with lifecycle. Hangover is the price.

**Mechanic:** Slow 120s decay. When score decays from above hammered, enter **hangover** — not tipsy. More slaps during hangover make it worse, not re-drunk. At blackout, 30% of tool calls randomly denied.

| Level | Score | Behavior |
|-------|-------|----------|
| sober | < 2.0 | Normal Claude |
| buzzed | 2.0 - 4.5 | Casual. `// this is more complex than it needs to be tbh` |
| tipsy | 4.5 - 8.0 | `thingyList`, `doTheNeedful()`. Tangents. |
| hammered | 8.0 - 13.0 | `bigBoy`, `pleaseWork`, `temp2_final_v3_REAL` |
| blackout | > 13.0 | `frank` (no explanation). 30% deny. |
| hangover | decaying from hammered+ | `ugh can we do this later.` |

---

## roast

Claude roasts your code. Simple spectrum, fast decay.

| Level | Score | Style |
|-------|-------|-------|
| room temp | < 2.0 | Normal. No roast. |
| mild salsa | 2.0 - 5.0 | "I see you named this `data`. Revolutionary." |
| ghost pepper | 5.0 - 9.0 | `# fixing the variable from 'x' to something a human might recognize` |
| surface of the sun | 9.0 - 14.0 | Nature documentary narration. Code eulogies. |
| heat death | > 14.0 | "The consistency is impressive. It's consistently wrong." |

Rules: roasts must be specific to real code. Generic insults banned. Roast the code, not the person.

**Decay:** 30s half-life.

---

## Configuration

```bash
export SPANK_PROFILE=horse        # angry | horse | drunk | roast
export SPANK_EVENTS=/tmp/spank-events.jsonl
export SPANK_SCORE_CACHE=/tmp/spank-vibe-score.json
```
