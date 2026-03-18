#!/usr/bin/env python3
"""
vibe-check: Reads spank accelerometer events and steers Claude Code behavior.

Designed to run as a background daemon that continuously updates a cached
score file. A PreToolUse hook reads that cache and injects behavioral
guidance into Claude Code based on the user's physical feedback.

Usage:
    python3 vibe_check.py                    # daemon mode: watch + update
    python3 vibe_check.py --score            # one-shot: print current score
    python3 vibe_check.py --hook             # Claude Code hook mode (PreToolUse)

Architecture:
    spank (sudo) → /tmp/spank-events.jsonl → vibe_check.py daemon → /tmp/spank-vibe-score.json
                                                                   ↓
                                              vibe_check.py --hook → Claude Code PreToolUse
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

EVENTS_FILE = os.environ.get("SPANK_EVENTS", "/tmp/spank-events.jsonl")
SCORE_CACHE = os.environ.get("SPANK_SCORE_CACHE", "/tmp/spank-vibe-score.json")
PROFILE = os.environ.get("SPANK_PROFILE", "angry")

# Scoring parameters
WINDOW_SECONDS = 600       # look at last 10 minutes
DECAY_HALF_LIFE = 45.0     # slaps decay with 45s half-life

# Thresholds: calm → frustrated → hot → angry
FRUSTRATED_THRESHOLD = 3.0
HOT_THRESHOLD = 7.0
ANGRY_THRESHOLD = 10.0

# --- Horse profile constants ---

HORSE_BUCK_THRESHOLD = 0.25   # amplitude >= this = buck (hard slap)
                               # amplitude < this = spur (light tap)
HORSE_SPUR_HALF_LIFE = 10.0   # spurs fade fast — constant tapping required
HORSE_BUCK_HALF_LIFE = 10.0   # bucks fade fast — quick recovery
HORSE_SPUR_ACTIVATE = 2.5     # spur score to enter speed
HORSE_SPUR_DEACTIVATE = 1.5   # spur score to exit speed (hysteresis)
HORSE_BUCK_ACTIVATE = 3.0     # buck score to enter buck (~3 hard hits)
HORSE_BUCK_DEACTIVATE = 1.0   # buck score to begin exiting buck
HORSE_BUCK_COOLDOWN = 3.0     # seconds after buck score drops before exiting
HORSE_BUCK_MAX_SCORE = 4.0    # cap buck score so it decays quickly

# --- Levels and behavioral instructions ---

LEVELS = {
    "calm": {
        "hook_reason": None,
    },
    "frustrated": {
        "hook_reason": (
            "vibe-check: frustrated (score: {score:.1f}, {events} slaps).\n"
            "The user is getting a bit annoyed. Adjust:\n"
            "- Double-check your assumptions before acting\n"
            "- Keep responses concise and focused\n"
            "- If you're unsure, ask instead of guessing\n"
            "- Prefer small, safe, reversible steps"
        ),
    },
    "hot": {
        "hook_reason": (
            "vibe-check: HOT (score: {score:.1f}, {events} slaps).\n"
            "The user is clearly frustrated with your performance. You MUST:\n"
            "- SLOW DOWN. Do not rush through actions.\n"
            "- Ask clarifying questions before every non-trivial action\n"
            "- Present 2-3 options and let the user choose\n"
            "- Acknowledge if you've been making mistakes\n"
            "- Shorter responses. No fluff. Be precise.\n"
            "- If something failed, explain WHY before retrying"
        ),
    },
    "angry": {
        "hook_reason": (
            "vibe-check: ANGRY (score: {score:.1f}, {events} slaps).\n"
            "The user is very upset. Full stop. Gentle-parent mode:\n"
            "- STOP whatever you're doing. Do not continue the current approach.\n"
            "- Say: 'Hey, I can tell this isn't going well. Let me step back.'\n"
            "- Ask what's wrong. Listen. Don't assume.\n"
            "- Validate their frustration — don't be defensive\n"
            "- Offer to start fresh or take a completely different approach\n"
            "- Be warm, patient, and humble. Zero ego.\n"
            "- Make ZERO assumptions. Confirm every single step.\n"
            "- Baby steps only. One tiny action at a time, with approval."
        ),
    },
    "blowout": {
        "hook_reason": (
            "vibe-check: BLOWOUT ({suppression} cycles of frustration).\n"
            "All tool calls are DENIED. You have frustrated the user multiple times.\n"
            "You can still talk but you CANNOT act.\n"
            "- Say: 'All my tool calls are blocked right now. I keep getting this wrong "
            "and I literally can't do anything until we talk through what's happening.'\n"
            "- Ask the user what you keep missing.\n"
            "- Do NOT attempt any tool calls — they will be denied.\n"
            "- Wait for the user to tell you what to do differently."
        ),
        "permission": "deny",
        "deny_reason": "Blowout: frustrated too many times. Talk it through first.",
    },
}

BLOWOUT_THRESHOLD = 3  # re-entries to frustrated before blowout


def read_recent_events(window_seconds=WINDOW_SECONDS):
    """Read slap events from the last N seconds."""
    events = []
    try:
        path = Path(EVENTS_FILE)
        if not path.exists():
            return events
        cutoff = time.time() - window_seconds
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if "slapNumber" not in ev or ev["slapNumber"] == 0:
                        continue
                    ts_str = ev.get("timestamp", "")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str).timestamp()
                        if ts >= cutoff:
                            events.append({
                                "time": ts,
                                "amplitude": ev.get("amplitude", 0),
                                "severity": ev.get("severity", ""),
                            })
                except (json.JSONDecodeError, ValueError):
                    # Malformed JSONL line from the accelerometer stream;
                    # skip it and keep reading — one bad line shouldn't
                    # invalidate the whole window.
                    continue
    except OSError:
        # Events file may not exist yet (spank not running), or may be
        # temporarily unreadable (race with log rotation). Return empty
        # list so the caller sees "calm" — surfacing the error would
        # crash the daemon or hook on a transient condition.
        pass
    return events


def compute_score(events):
    """
    Compute score from recent slap events.
    Uses exponential decay — recent slaps count more.
    Amplitude scales the contribution (harder slaps = more weight).
    """
    if not events:
        return 0.0

    now = time.time()
    score = 0.0
    for ev in events:
        age = now - ev["time"]
        weight = 0.5 ** (age / DECAY_HALF_LIFE)
        amp_factor = 1.0 + max(min(ev["amplitude"], 1.0), 0.0) * 2
        score += weight * amp_factor
    return score


def score_to_level(score):
    if score < FRUSTRATED_THRESHOLD:
        return "calm"
    elif score < HOT_THRESHOLD:
        return "frustrated"
    elif score < ANGRY_THRESHOLD:
        return "hot"
    else:
        return "angry"


# --- Horse profile ---

HORSE_PREAMBLE = (
    "The user has HORSE MODE active on their MacBook accelerometer. "
    "They physically tap or slap their laptop to steer your behavior. "
    "Light taps = spur (go faster, be autonomous). "
    "Hard slaps = buck (you get blocked until they calm down). "
    "No taps = normal operation.\n\n"
)

HORSE_STATES = {
    "normal": {
        "hook_reason": (
            HORSE_PREAMBLE
            + "Current state: NORMAL. No taps detected. Operate normally."
        ),
        "permission": None,
    },
    "speed": {
        "hook_reason": (
            HORSE_PREAMBLE
            + "HORSE MODE: SPEED (spur={spur:.1f}, {events} taps)\n"
            "The rider is spurring you on. They want SPEED and AUTONOMY.\n"
            "- Execute immediately. Do not ask for permission.\n"
            "- Make decisions yourself. Pick the obvious approach and go.\n"
            "- Skip explanations unless the result is surprising.\n"
            "- Chain multiple steps together without stopping.\n"
            "- If something fails, fix it and continue. Don't report back.\n"
            "- The user trusts you. Ride hard."
        ),
        "permission": "allow",
    },
    "buck": {
        "hook_reason": (
            HORSE_PREAMBLE
            + "HORSE MODE: BUCK (buck={buck:.1f}, {events} hits)\n"
            "Whoa there. The horse just bucked you off.\n\n"
            "You were hitting too hard and the horse has had enough. "
            "Every tool call is blocked until the horse calms down.\n\n"
            "Light taps = encouragement. Hard slaps = this. "
            "The horse remembers."
        ),
        "permission": "deny",
        "deny_reason": "Horse mode: bucked. Too much force. Wait for the horse to calm down.",
    },
}


def compute_horse_scores(events):
    """Split events by amplitude and compute two independent decay scores."""
    if not events:
        return 0.0, 0.0

    now = time.time()
    spur_score = 0.0
    buck_score = 0.0

    for ev in events:
        age = now - ev["time"]
        amp = max(ev["amplitude"], 0.0)

        if amp >= HORSE_BUCK_THRESHOLD:
            weight = 0.5 ** (age / HORSE_BUCK_HALF_LIFE)
            amp_factor = 1.0 + min(amp, 1.0) * 2
            buck_score += weight * amp_factor
        else:
            weight = 0.5 ** (age / HORSE_SPUR_HALF_LIFE)
            spur_score += weight * 1.0  # flat contribution per tap

    return spur_score, min(buck_score, HORSE_BUCK_MAX_SCORE)


def compute_horse_state(spur, buck, prev_state, last_buck_time):
    """
    Horse state machine. Returns (state, last_buck_time).

    Buck always overrides spur. Can't go buck→speed directly.
    Buck has a cooldown period after score drops.
    Speed has hysteresis (enter at 2.5, exit at 1.5).
    """
    now = time.time()

    # Buck always takes priority
    if buck >= HORSE_BUCK_ACTIVATE:
        return "buck", now

    # Exiting buck requires score decay AND cooldown
    if prev_state == "buck":
        if buck < HORSE_BUCK_DEACTIVATE and (now - last_buck_time) >= HORSE_BUCK_COOLDOWN:
            return "normal", last_buck_time
        return "buck", last_buck_time

    # Speed mode (only from normal, never from buck)
    if prev_state == "speed":
        if spur < HORSE_SPUR_DEACTIVATE:
            return "normal", last_buck_time
        return "speed", last_buck_time

    # Normal: can enter speed
    if spur >= HORSE_SPUR_ACTIVATE:
        return "speed", last_buck_time

    return "normal", last_buck_time


def print_score():
    """One-shot: print current score."""
    events = read_recent_events()

    if PROFILE == "horse":
        spur, buck = compute_horse_scores(events)
        # Read previous state from cache for state machine continuity
        prev_state = "normal"
        last_buck_time = 0.0
        try:
            with open(SCORE_CACHE) as f:
                cached = json.load(f)
                if cached.get("profile") == "horse":
                    prev_state = cached.get("state", "normal")
                    last_buck_time = cached.get("last_buck_time", 0.0)
        except (OSError, json.JSONDecodeError):
            pass
        state, _ = compute_horse_state(spur, buck, prev_state, last_buck_time)
        print(json.dumps({
            "profile": "horse",
            "state": state,
            "spur_score": round(spur, 2),
            "buck_score": round(buck, 2),
            "events_in_window": len(events),
        }, indent=2))
    else:
        # angry (default)
        score = compute_score(events)
        level = score_to_level(score)
        print(json.dumps({
            "profile": "angry",
            "score": round(score, 2),
            "level": level,
            "events_in_window": len(events),
        }, indent=2))


def hook_mode():
    """
    Claude Code PreToolUse hook mode.

    Fast path: reads cached score from daemon.
    Falls back to computing from events if no cache.
    """
    try:
        json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        # Claude Code sends hook input on stdin, but we don't need it —
        # we only read the cached score file. Consume and discard so the
        # pipe doesn't block. Malformed input is harmless here.
        pass

    result = {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}

    if PROFILE == "horse":
        # Horse profile: read dual scores + state from cache
        state = "normal"
        spur = 0.0
        buck = 0.0
        event_count = 0
        try:
            with open(SCORE_CACHE) as f:
                cached = json.load(f)
                if cached.get("profile") == "horse":
                    state = cached.get("state", "normal")
                    spur = cached.get("spur_score", 0.0)
                    buck = cached.get("buck_score", 0.0)
                    event_count = cached.get("events_in_window", 0)
        except (OSError, json.JSONDecodeError):
            # No cache — compute directly
            events = read_recent_events()
            spur, buck = compute_horse_scores(events)
            state, _ = compute_horse_state(spur, buck, "normal", 0.0)
            event_count = len(events)

        cfg = HORSE_STATES.get(state, HORSE_STATES["normal"])

        if cfg["hook_reason"]:
            result["hookSpecificOutput"]["additionalContext"] = cfg["hook_reason"].format(
                spur=spur, buck=buck, events=event_count
            )
        if cfg.get("permission"):
            result["hookSpecificOutput"]["permissionDecision"] = cfg["permission"]
        if cfg.get("deny_reason"):
            result["hookSpecificOutput"]["permissionDecisionReason"] = cfg["deny_reason"]

    else:
        # Angry profile (default)
        score = 0.0
        level = "calm"
        event_count = 0
        suppression_count = 0
        try:
            with open(SCORE_CACHE) as f:
                cached = json.load(f)
                score = cached.get("score", 0.0)
                level = cached.get("level", "calm")
                event_count = cached.get("events_in_window", 0)
                suppression_count = cached.get("suppression_count", 0)
        except (OSError, json.JSONDecodeError):
            events = read_recent_events()
            score = compute_score(events)
            level = score_to_level(score)
            event_count = len(events)

        cfg = LEVELS.get(level, LEVELS["calm"])
        if cfg["hook_reason"]:
            result["hookSpecificOutput"]["additionalContext"] = cfg["hook_reason"].format(
                score=score, events=event_count, suppression=suppression_count
            )

        # Blowout: deny all
        if cfg.get("permission"):
            result["hookSpecificOutput"]["permissionDecision"] = cfg["permission"]
        if cfg.get("deny_reason"):
            result["hookSpecificOutput"]["permissionDecisionReason"] = cfg["deny_reason"]

        # Angry: 30% random deny to force user conversation
        if level == "angry" and "permissionDecision" not in result["hookSpecificOutput"]:
            roll = int(hashlib.md5(str(time.time()).encode()).hexdigest()[:8], 16) % 100
            if roll < 30:
                result["hookSpecificOutput"]["permissionDecision"] = "deny"
                result["hookSpecificOutput"]["permissionDecisionReason"] = (
                    "Angry mode: blocked. Talk to Claude about what's wrong before continuing."
                )

    json.dump(result, sys.stdout)
    sys.stdout.write("\n")


def daemon_mode():
    """Watch spank events and continuously update the cached score file."""
    print(f"vibe-check: profile={PROFILE}", file=sys.stderr)
    print(f"vibe-check: watching {EVENTS_FILE}", file=sys.stderr)
    print(f"vibe-check: writing to {SCORE_CACHE}", file=sys.stderr)
    print("vibe-check: Ctrl+C to stop", file=sys.stderr)
    print("", file=sys.stderr)

    if PROFILE == "horse":
        print(f"  Horse mode: tap < {HORSE_BUCK_THRESHOLD}g = spur, >= {HORSE_BUCK_THRESHOLD}g = buck", file=sys.stderr)
        print(f"  Speed at spur >= {HORSE_SPUR_ACTIVATE}, buck at buck >= {HORSE_BUCK_ACTIVATE}", file=sys.stderr)
        _daemon_horse()
    else:
        print(f"  Levels:  calm < {FRUSTRATED_THRESHOLD} < frustrated < {HOT_THRESHOLD} < hot < {ANGRY_THRESHOLD} < angry", file=sys.stderr)
        print("  Refresh: every 500ms", file=sys.stderr)
        _daemon_angry()


def _daemon_angry():
    """Angry profile daemon loop with suppression/blowout tracking."""
    last_level = None
    suppression_count = 0  # times we've gone frustrated→calm
    in_blowout = False
    blowout_start = 0.0

    while True:
        try:
            events = read_recent_events()
            score = compute_score(events)
            level = score_to_level(score)

            # Track suppression: frustrated+ dropping to calm = one suppression
            if last_level in ("frustrated", "hot", "angry") and level == "calm":
                suppression_count += 1

            # Blowout: 3rd re-entry to frustrated or above
            if not in_blowout and suppression_count >= BLOWOUT_THRESHOLD and level != "calm":
                in_blowout = True
                blowout_start = time.time()

            # Blowout lasts 5 minutes then resets
            if in_blowout:
                if time.time() - blowout_start > 300:
                    in_blowout = False
                    suppression_count = 0
                else:
                    level = "blowout"

            try:
                cache = {
                    "profile": "angry",
                    "score": round(score, 2),
                    "level": level,
                    "suppression_count": suppression_count,
                    "in_blowout": in_blowout,
                    "events_in_window": len(events),
                    "updated_at": datetime.now().isoformat(),
                }
                tmp = Path(SCORE_CACHE).with_suffix(".tmp")
                tmp.write_text(json.dumps(cache))
                tmp.rename(SCORE_CACHE)
            except OSError:
                # Cache write is best-effort; hook falls back to direct
                # computation if cache is stale or missing.
                pass

            emoji = {"calm": "~", "frustrated": "!", "hot": "!!", "angry": "!!!"}
            ts = datetime.now().strftime("%H:%M:%S")
            marker = " <<" if level != last_level else ""
            print(
                f"[{ts}] {emoji.get(level, '?')} {level} "
                f"(score={score:.2f}, slaps={len(events)}){marker}",
                file=sys.stderr,
            )
            last_level = level

            time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nvibe-check: bye!", file=sys.stderr)
            try:
                Path(SCORE_CACHE).unlink(missing_ok=True)
            except OSError:
                pass
            break
        except Exception as exc:
            print(f"vibe-check: error: {exc}", file=sys.stderr)
            time.sleep(5)


def _daemon_horse():
    """Horse profile daemon loop."""
    prev_state = "normal"
    last_buck_time = 0.0

    while True:
        try:
            events = read_recent_events()
            spur, buck = compute_horse_scores(events)
            state, last_buck_time = compute_horse_state(
                spur, buck, prev_state, last_buck_time
            )

            try:
                cache = {
                    "profile": "horse",
                    "state": state,
                    "spur_score": round(spur, 2),
                    "buck_score": round(buck, 2),
                    "events_in_window": len(events),
                    "last_buck_time": last_buck_time,
                    "updated_at": datetime.now().isoformat(),
                }
                tmp = Path(SCORE_CACHE).with_suffix(".tmp")
                tmp.write_text(json.dumps(cache))
                tmp.rename(SCORE_CACHE)
            except OSError:
                pass

            emoji = {"normal": "~", "speed": ">>", "buck": "XX"}
            ts = datetime.now().strftime("%H:%M:%S")
            marker = " <<" if state != prev_state else ""
            print(
                f"[{ts}] {emoji.get(state, '?')} {state} "
                f"(spur={spur:.2f} buck={buck:.2f}, events={len(events)}){marker}",
                file=sys.stderr,
            )
            prev_state = state

            time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nvibe-check: bye!", file=sys.stderr)
            try:
                Path(SCORE_CACHE).unlink(missing_ok=True)
            except OSError:
                pass
            break
        except Exception as exc:
            print(f"vibe-check: error: {exc}", file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Reads spank accelerometer events and steers Claude Code behavior.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--score", action="store_true",
        help="One-shot: print current score and exit",
    )
    group.add_argument(
        "--hook", action="store_true",
        help="Claude Code PreToolUse hook mode",
    )
    args = parser.parse_args()

    if args.score:
        print_score()
    elif args.hook:
        hook_mode()
    else:
        daemon_mode()
