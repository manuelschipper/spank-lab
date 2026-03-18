"""Tests for the horse profile in vibe_check."""

import json
import sys
import time
from io import StringIO
from pathlib import Path

import pytest

# Ensure the module directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

import vibe_check


# ---------------------------------------------------------------------------
# 1. compute_horse_scores — event splitting and decay
# ---------------------------------------------------------------------------

class TestComputeHorseScores:
    """Verify amplitude-based split and per-channel decay math."""

    def test_empty_events(self):
        """No events returns (0, 0)."""
        assert vibe_check.compute_horse_scores([]) == (0.0, 0.0)

    def test_light_taps_only_go_to_spur(self, monkeypatch):
        """Events with amplitude < HORSE_BUCK_THRESHOLD contribute only to spur_score."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        events = [
            {"time": now, "amplitude": 0.05},
            {"time": now, "amplitude": 0.10},
            {"time": now, "amplitude": 0.14},
        ]
        spur, buck = vibe_check.compute_horse_scores(events)
        # Each light tap contributes 1.0 (flat) with weight=1.0 (age=0)
        assert spur == pytest.approx(3.0)
        assert buck == pytest.approx(0.0)

    def test_hard_slaps_only_go_to_buck(self, monkeypatch):
        """Events with amplitude >= HORSE_BUCK_THRESHOLD contribute only to buck_score."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        threshold = vibe_check.HORSE_BUCK_THRESHOLD
        events = [
            {"time": now, "amplitude": threshold},
            {"time": now, "amplitude": 0.50},
            {"time": now, "amplitude": 1.00},
        ]
        spur, buck = vibe_check.compute_horse_scores(events)
        assert spur == pytest.approx(0.0)
        # amp=threshold(0.25) -> 1 + min(0.25,1)*2 = 1.50
        # amp=0.50 -> 1 + min(0.50,1)*2 = 2.00
        # amp=1.00 -> 1 + min(1.00,1)*2 = 3.00
        raw = 1.50 + 2.00 + 3.00
        assert buck == pytest.approx(min(raw, vibe_check.HORSE_BUCK_MAX_SCORE))

    def test_mixed_events_split_correctly(self, monkeypatch):
        """Light taps go to spur, hard slaps go to buck."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        threshold = vibe_check.HORSE_BUCK_THRESHOLD  # 0.25
        events = [
            {"time": now, "amplitude": 0.05},        # spur (below threshold)
            {"time": now, "amplitude": 0.50},         # buck (above threshold)
            {"time": now, "amplitude": 0.10},         # spur (below threshold)
            {"time": now, "amplitude": threshold},    # buck (at threshold)
        ]
        spur, buck = vibe_check.compute_horse_scores(events)
        # spur: 2 light taps at age=0 -> 2 * 1.0 = 2.0
        assert spur == pytest.approx(2.0)
        # buck: amp=0.50 -> 2.0, amp=threshold(0.25) -> 1.5
        assert buck == pytest.approx(2.0 + 1.5)

    def test_boundary_amplitude_goes_to_buck(self, monkeypatch):
        """Amplitude exactly at HORSE_BUCK_THRESHOLD is a buck."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        events = [{"time": now, "amplitude": vibe_check.HORSE_BUCK_THRESHOLD}]
        spur, buck = vibe_check.compute_horse_scores(events)
        assert spur == pytest.approx(0.0)
        assert buck > 0.0

    def test_spur_decay_uses_spur_half_life(self, monkeypatch):
        """Spur events decay with HORSE_SPUR_HALF_LIFE (20s)."""
        now = 1000.0
        hl = vibe_check.HORSE_SPUR_HALF_LIFE
        monkeypatch.setattr(time, "time", lambda: now)

        events = [{"time": now - hl, "amplitude": 0.05}]
        spur, buck = vibe_check.compute_horse_scores(events)
        # After one half-life: weight=0.5, contribution=0.5 * 1.0 = 0.5
        assert spur == pytest.approx(0.5)
        assert buck == pytest.approx(0.0)

    def test_buck_decay_uses_buck_half_life(self, monkeypatch):
        """Buck events decay with HORSE_BUCK_HALF_LIFE (15s)."""
        now = 1000.0
        hl = vibe_check.HORSE_BUCK_HALF_LIFE
        monkeypatch.setattr(time, "time", lambda: now)

        events = [{"time": now - hl, "amplitude": 0.50}]
        spur, buck = vibe_check.compute_horse_scores(events)
        assert spur == pytest.approx(0.0)
        # After one half-life: weight=0.5, amp_factor=1+0.5*2=2.0
        assert buck == pytest.approx(0.5 * 2.0)

    def test_spur_and_buck_use_configured_half_lives(self, monkeypatch):
        """Spur and buck channels each decay using their own half-life constant."""
        now = 1000.0
        age = 30.0
        monkeypatch.setattr(time, "time", lambda: now)

        spur_events = [{"time": now - age, "amplitude": 0.05}]
        buck_events = [{"time": now - age, "amplitude": 0.50}]

        spur, _ = vibe_check.compute_horse_scores(spur_events)
        _, buck = vibe_check.compute_horse_scores(buck_events)

        spur_weight = 0.5 ** (age / vibe_check.HORSE_SPUR_HALF_LIFE)
        buck_weight = 0.5 ** (age / vibe_check.HORSE_BUCK_HALF_LIFE)
        # Spur: flat 1.0 contribution * weight
        assert spur == pytest.approx(spur_weight * 1.0)
        # Buck: amp_factor = 1 + min(0.50, 1.0)*2 = 2.0
        assert buck == pytest.approx(buck_weight * 2.0)

    def test_negative_amplitude_clamped_to_zero(self, monkeypatch):
        """Negative amplitude is treated as 0 via max(amp, 0.0)."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        events = [{"time": now, "amplitude": -0.5}]
        spur, buck = vibe_check.compute_horse_scores(events)
        # amp=0 < HORSE_BUCK_THRESHOLD -> spur channel, flat 1.0 contribution
        assert spur == pytest.approx(1.0)
        assert buck == pytest.approx(0.0)

    def test_buck_amplitude_capped_at_one(self, monkeypatch):
        """Buck amp_factor uses min(amp, 1.0) — amplitudes above 1 are capped."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        events = [{"time": now, "amplitude": 5.0}]
        spur, buck = vibe_check.compute_horse_scores(events)
        # amp_factor = 1 + min(5.0, 1.0)*2 = 3.0 (same as amp=1.0)
        assert buck == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# 2. compute_horse_state — state machine transitions
# ---------------------------------------------------------------------------

class TestComputeHorseState:
    """Verify state machine transitions, hysteresis, cooldown, and overrides."""

    def test_normal_stays_normal_when_spur_low(self, monkeypatch):
        """Normal stays normal when spur < HORSE_SPUR_ACTIVATE (2.5)."""
        monkeypatch.setattr(time, "time", lambda: 1000.0)
        state, lbt = vibe_check.compute_horse_state(
            spur=1.0, buck=0.0, prev_state="normal", last_buck_time=0.0
        )
        assert state == "normal"

    def test_normal_to_speed_when_spur_high(self, monkeypatch):
        """Normal -> speed when spur >= HORSE_SPUR_ACTIVATE (2.5)."""
        monkeypatch.setattr(time, "time", lambda: 1000.0)
        state, lbt = vibe_check.compute_horse_state(
            spur=2.5, buck=0.0, prev_state="normal", last_buck_time=0.0
        )
        assert state == "speed"

    def test_normal_to_speed_above_activate(self, monkeypatch):
        """Normal -> speed when spur well above activate threshold."""
        monkeypatch.setattr(time, "time", lambda: 1000.0)
        state, lbt = vibe_check.compute_horse_state(
            spur=5.0, buck=0.0, prev_state="normal", last_buck_time=0.0
        )
        assert state == "speed"

    def test_speed_stays_speed_between_thresholds(self, monkeypatch):
        """Speed stays speed when spur is between deactivate (1.5) and activate (2.5)."""
        monkeypatch.setattr(time, "time", lambda: 1000.0)
        state, lbt = vibe_check.compute_horse_state(
            spur=2.0, buck=0.0, prev_state="speed", last_buck_time=0.0
        )
        assert state == "speed"

    def test_speed_stays_at_deactivate_boundary(self, monkeypatch):
        """Speed stays speed when spur == deactivate threshold (1.5)."""
        monkeypatch.setattr(time, "time", lambda: 1000.0)
        state, lbt = vibe_check.compute_horse_state(
            spur=1.5, buck=0.0, prev_state="speed", last_buck_time=0.0
        )
        assert state == "speed"

    def test_speed_to_normal_when_spur_drops_below_deactivate(self, monkeypatch):
        """Speed -> normal when spur < HORSE_SPUR_DEACTIVATE (1.5) — hysteresis."""
        monkeypatch.setattr(time, "time", lambda: 1000.0)
        state, lbt = vibe_check.compute_horse_state(
            spur=1.4, buck=0.0, prev_state="speed", last_buck_time=0.0
        )
        assert state == "normal"

    def test_buck_overrides_speed_from_normal(self, monkeypatch):
        """Buck overrides when buck >= HORSE_BUCK_ACTIVATE, from normal."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)
        state, lbt = vibe_check.compute_horse_state(
            spur=0.0, buck=vibe_check.HORSE_BUCK_ACTIVATE,
            prev_state="normal", last_buck_time=0.0
        )
        assert state == "buck"
        assert lbt == now

    def test_buck_overrides_speed_from_speed(self, monkeypatch):
        """Buck overrides when buck >= HORSE_BUCK_ACTIVATE, even from speed."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)
        state, lbt = vibe_check.compute_horse_state(
            spur=5.0, buck=vibe_check.HORSE_BUCK_ACTIVATE,
            prev_state="speed", last_buck_time=0.0
        )
        assert state == "buck"
        assert lbt == now

    def test_buck_stays_when_score_above_deactivate(self, monkeypatch):
        """Buck stays buck when buck score >= HORSE_BUCK_DEACTIVATE (1.0)."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)
        state, lbt = vibe_check.compute_horse_state(
            spur=0.0, buck=1.5, prev_state="buck", last_buck_time=now - 100
        )
        assert state == "buck"

    def test_buck_stays_when_score_low_but_cooldown_not_elapsed(self, monkeypatch):
        """Buck stays if score < deactivate BUT cooldown hasn't elapsed."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)
        # last_buck_time was 2 seconds ago, cooldown is 5s
        state, lbt = vibe_check.compute_horse_state(
            spur=0.0, buck=0.5, prev_state="buck", last_buck_time=now - 2.0
        )
        assert state == "buck"

    def test_buck_exits_when_score_low_and_cooldown_elapsed(self, monkeypatch):
        """Buck -> normal when buck < deactivate AND cooldown has elapsed."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)
        # last_buck_time was 10 seconds ago, cooldown is 5s
        state, lbt = vibe_check.compute_horse_state(
            spur=0.0, buck=0.5, prev_state="buck", last_buck_time=now - 10.0
        )
        assert state == "normal"

    def test_buck_exits_at_exact_cooldown_boundary(self, monkeypatch):
        """Buck -> normal when cooldown is exactly elapsed (>= check)."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)
        cooldown = vibe_check.HORSE_BUCK_COOLDOWN
        state, lbt = vibe_check.compute_horse_state(
            spur=0.0, buck=0.5, prev_state="buck", last_buck_time=now - cooldown
        )
        assert state == "normal"

    def test_buck_to_normal_not_speed_even_with_high_spur(self, monkeypatch):
        """Exiting buck goes to normal, NOT speed, even if spur is very high.
        The code checks prev_state == 'buck' before speed logic, and exits to 'normal'.
        """
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)
        state, lbt = vibe_check.compute_horse_state(
            spur=10.0, buck=0.5, prev_state="buck", last_buck_time=now - 20.0
        )
        assert state == "normal"

    def test_buck_preserves_last_buck_time_while_active(self, monkeypatch):
        """While in buck (not exiting), last_buck_time is preserved, not updated."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)
        original_lbt = now - 3.0  # buck started 3 seconds ago

        # Still in buck because score >= deactivate
        state, lbt = vibe_check.compute_horse_state(
            spur=0.0, buck=1.5, prev_state="buck", last_buck_time=original_lbt
        )
        assert state == "buck"
        assert lbt == original_lbt  # preserved, not reset to now

    def test_buck_updates_last_buck_time_on_fresh_activation(self, monkeypatch):
        """When buck freshly activates (score >= activate), last_buck_time = now."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)
        state, lbt = vibe_check.compute_horse_state(
            spur=0.0, buck=3.0, prev_state="normal", last_buck_time=0.0
        )
        assert state == "buck"
        assert lbt == now

    def test_buck_reactivates_updates_time_even_from_buck(self, monkeypatch):
        """If buck score jumps back above activate while already in buck,
        last_buck_time resets to now (the >= ACTIVATE check runs first)."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)
        state, lbt = vibe_check.compute_horse_state(
            spur=0.0, buck=vibe_check.HORSE_BUCK_ACTIVATE,
            prev_state="buck", last_buck_time=now - 50.0
        )
        assert state == "buck"
        # The >= ACTIVATE check fires first, returning (buck, now)
        assert lbt == now

    def test_full_lifecycle_normal_speed_buck_normal(self, monkeypatch):
        """Walk through a full lifecycle: normal -> speed -> buck -> normal."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        # Step 1: normal -> speed (spur high)
        state, lbt = vibe_check.compute_horse_state(
            spur=3.0, buck=0.0, prev_state="normal", last_buck_time=0.0
        )
        assert state == "speed"

        # Step 2: speed -> buck (hard slap while speeding)
        state, lbt = vibe_check.compute_horse_state(
            spur=3.0, buck=vibe_check.HORSE_BUCK_ACTIVATE,
            prev_state="speed", last_buck_time=lbt
        )
        assert state == "buck"
        assert lbt == now

        # Step 3: buck stays (cooldown not done — only 1s elapsed)
        monkeypatch.setattr(time, "time", lambda: now + 1.0)
        state, lbt = vibe_check.compute_horse_state(
            spur=3.0, buck=0.5, prev_state="buck", last_buck_time=lbt
        )
        assert state == "buck"

        # Step 4: buck -> normal (score low + cooldown elapsed)
        monkeypatch.setattr(time, "time", lambda: now + 20.0)
        state, lbt = vibe_check.compute_horse_state(
            spur=3.0, buck=0.5, prev_state="buck", last_buck_time=now
        )
        assert state == "normal"


# ---------------------------------------------------------------------------
# 3. Horse hook output
# ---------------------------------------------------------------------------

class TestHorseHookOutput:
    """Test the PreToolUse hook JSON output for horse profile."""

    def _run_horse_hook(self, monkeypatch, cache_data, tmp_path):
        """Helper: write horse cache, set profile to horse, run hook_mode."""
        cache_file = tmp_path / "score.json"
        cache_file.write_text(json.dumps(cache_data))
        monkeypatch.setattr(vibe_check, "SCORE_CACHE", str(cache_file))
        monkeypatch.setattr(vibe_check, "PROFILE", "horse")

        monkeypatch.setattr("sys.stdin", StringIO('{"hook_name": "PreToolUse"}'))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        vibe_check.hook_mode()

        captured.seek(0)
        return json.loads(captured.read())

    def test_normal_state_has_preamble_context_no_permission(self, monkeypatch, tmp_path):
        """Normal state: additionalContext with preamble, no permissionDecision."""
        result = self._run_horse_hook(monkeypatch, {
            "profile": "horse",
            "state": "normal",
            "spur_score": 0.5,
            "buck_score": 0.0,
            "events_in_window": 1,
        }, tmp_path)

        hook = result["hookSpecificOutput"]
        assert hook["hookEventName"] == "PreToolUse"
        assert "additionalContext" in hook
        assert "NORMAL" in hook["additionalContext"]
        assert "permissionDecision" not in hook

    def test_speed_state_allow_with_context(self, monkeypatch, tmp_path):
        """Speed state: permissionDecision 'allow' + context with spur score."""
        result = self._run_horse_hook(monkeypatch, {
            "profile": "horse",
            "state": "speed",
            "spur_score": 3.2,
            "buck_score": 0.0,
            "events_in_window": 5,
        }, tmp_path)

        hook = result["hookSpecificOutput"]
        assert hook["permissionDecision"] == "allow"
        ctx = hook["additionalContext"]
        assert "SPEED" in ctx
        assert "3.2" in ctx
        assert "5 taps" in ctx

    def test_buck_state_deny_with_reason_and_context(self, monkeypatch, tmp_path):
        """Buck state: permissionDecision 'deny' + deny_reason + context."""
        result = self._run_horse_hook(monkeypatch, {
            "profile": "horse",
            "state": "buck",
            "spur_score": 0.0,
            "buck_score": 3.5,
            "events_in_window": 8,
        }, tmp_path)

        hook = result["hookSpecificOutput"]
        assert hook["permissionDecision"] == "deny"
        assert "permissionDecisionReason" in hook
        assert "bucked" in hook["permissionDecisionReason"].lower()
        ctx = hook["additionalContext"]
        assert "BUCK" in ctx
        assert "3.5" in ctx
        assert "8 hits" in ctx

    def test_hook_output_is_valid_json_line(self, monkeypatch, tmp_path):
        """Output must be valid JSON followed by a newline."""
        cache_file = tmp_path / "score.json"
        cache_file.write_text(json.dumps({
            "profile": "horse",
            "state": "normal",
            "spur_score": 0.0,
            "buck_score": 0.0,
            "events_in_window": 0,
        }))
        monkeypatch.setattr(vibe_check, "SCORE_CACHE", str(cache_file))
        monkeypatch.setattr(vibe_check, "PROFILE", "horse")
        monkeypatch.setattr("sys.stdin", StringIO("{}"))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        vibe_check.hook_mode()

        raw = captured.getvalue()
        assert raw.endswith("\n")
        json.loads(raw)

    def test_horse_hook_fallback_when_no_cache(self, monkeypatch, tmp_path):
        """When cache is missing, hook computes from events file directly."""
        monkeypatch.setattr(vibe_check, "SCORE_CACHE", str(tmp_path / "missing.json"))
        monkeypatch.setattr(vibe_check, "EVENTS_FILE", str(tmp_path / "missing.jsonl"))
        monkeypatch.setattr(vibe_check, "PROFILE", "horse")

        monkeypatch.setattr("sys.stdin", StringIO("{}"))
        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        vibe_check.hook_mode()

        result = json.loads(captured.getvalue())
        hook = result["hookSpecificOutput"]
        assert hook["hookEventName"] == "PreToolUse"
        # No events -> normal state -> preamble context, no permission
        assert "additionalContext" in hook
        assert "NORMAL" in hook["additionalContext"]
        assert "permissionDecision" not in hook

    def test_horse_hook_ignores_non_horse_cache(self, monkeypatch, tmp_path):
        """If cache has profile != 'horse', hook falls back to defaults."""
        cache_file = tmp_path / "score.json"
        cache_file.write_text(json.dumps({
            "profile": "frustration",
            "score": 5.0,
            "level": "hot",
            "events_in_window": 10,
        }))
        monkeypatch.setattr(vibe_check, "SCORE_CACHE", str(cache_file))
        monkeypatch.setattr(vibe_check, "PROFILE", "horse")
        monkeypatch.setattr(vibe_check, "EVENTS_FILE", str(tmp_path / "missing.jsonl"))

        monkeypatch.setattr("sys.stdin", StringIO("{}"))
        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        vibe_check.hook_mode()

        result = json.loads(captured.getvalue())
        hook = result["hookSpecificOutput"]
        # Should see normal horse state (preamble context), not frustration output
        assert "additionalContext" in hook
        assert "NORMAL" in hook["additionalContext"]
        assert "permissionDecision" not in hook


# ---------------------------------------------------------------------------
# 4. HORSE_STATES config structure
# ---------------------------------------------------------------------------

class TestHorseStatesConfig:
    """Verify the HORSE_STATES dict has the expected keys and values."""

    def test_all_three_states_present(self):
        assert set(vibe_check.HORSE_STATES.keys()) == {"normal", "speed", "buck"}

    def test_normal_has_hook_reason_with_preamble(self):
        reason = vibe_check.HORSE_STATES["normal"]["hook_reason"]
        assert reason is not None
        assert "NORMAL" in reason
        assert "HORSE MODE" in reason

    def test_normal_has_no_permission(self):
        assert vibe_check.HORSE_STATES["normal"]["permission"] is None

    def test_speed_permission_is_allow(self):
        assert vibe_check.HORSE_STATES["speed"]["permission"] == "allow"

    def test_speed_has_hook_reason(self):
        assert vibe_check.HORSE_STATES["speed"]["hook_reason"] is not None
        assert "SPEED" in vibe_check.HORSE_STATES["speed"]["hook_reason"]

    def test_buck_permission_is_deny(self):
        assert vibe_check.HORSE_STATES["buck"]["permission"] == "deny"

    def test_buck_has_deny_reason(self):
        assert "deny_reason" in vibe_check.HORSE_STATES["buck"]
        assert len(vibe_check.HORSE_STATES["buck"]["deny_reason"]) > 0

    def test_buck_has_hook_reason(self):
        assert vibe_check.HORSE_STATES["buck"]["hook_reason"] is not None
        assert "BUCK" in vibe_check.HORSE_STATES["buck"]["hook_reason"]

    def test_speed_hook_reason_has_format_placeholders(self):
        """Speed hook_reason should accept spur, buck, events format vars."""
        reason = vibe_check.HORSE_STATES["speed"]["hook_reason"]
        formatted = reason.format(spur=1.0, buck=0.0, events=3)
        assert "1.0" in formatted

    def test_buck_hook_reason_has_format_placeholders(self):
        """Buck hook_reason should accept spur, buck, events format vars."""
        reason = vibe_check.HORSE_STATES["buck"]["hook_reason"]
        formatted = reason.format(spur=0.0, buck=2.5, events=7)
        assert "2.5" in formatted


# ---------------------------------------------------------------------------
# 5. Horse constants sanity checks
# ---------------------------------------------------------------------------

class TestHorseConstants:
    """Guard against accidental constant changes that would break the profile."""

    def test_buck_threshold(self):
        assert vibe_check.HORSE_BUCK_THRESHOLD == 0.25

    def test_spur_and_buck_half_lives(self):
        """Both channels use the same half-life (10.0s)."""
        assert vibe_check.HORSE_SPUR_HALF_LIFE == 10.0
        assert vibe_check.HORSE_BUCK_HALF_LIFE == 10.0

    def test_buck_max_score_exists(self):
        """Buck score is capped to allow quick decay recovery."""
        assert vibe_check.HORSE_BUCK_MAX_SCORE == 4.0

    def test_spur_activate_greater_than_deactivate(self):
        """Hysteresis requires activate > deactivate."""
        assert vibe_check.HORSE_SPUR_ACTIVATE > vibe_check.HORSE_SPUR_DEACTIVATE

    def test_buck_activate_greater_than_deactivate(self):
        """Buck must have gap between activate and deactivate."""
        assert vibe_check.HORSE_BUCK_ACTIVATE > vibe_check.HORSE_BUCK_DEACTIVATE

    def test_buck_cooldown_positive(self):
        assert vibe_check.HORSE_BUCK_COOLDOWN > 0
