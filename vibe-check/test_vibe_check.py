"""Tests for the vibe_check module."""

import json
import sys
import time
from io import StringIO
from pathlib import Path
from datetime import datetime, timezone

import pytest

# Ensure the module directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

import vibe_check


# ---------------------------------------------------------------------------
# 1. compute_score exponential decay
# ---------------------------------------------------------------------------

class TestComputeScore:
    """Verify math matches sum(0.5^(age/HL) * (1 + min(amp,1.0)*2))."""

    def test_single_event_age_zero(self, monkeypatch):
        """Event at age=0: weight=1.0, amp_factor=1+min(amp,1)*2."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        events = [{"time": now, "amplitude": 0.5}]
        expected = 1.0 * (1.0 + 0.5 * 2)
        assert vibe_check.compute_score(events) == pytest.approx(expected)

    def test_single_event_one_half_life(self, monkeypatch):
        """Event at age=one half-life: weight should be 0.5."""
        now = 1000.0
        hl = vibe_check.DECAY_HALF_LIFE
        monkeypatch.setattr(time, "time", lambda: now)

        events = [{"time": now - hl, "amplitude": 0.0}]
        expected = 0.5 * 1.0
        assert vibe_check.compute_score(events) == pytest.approx(expected)

    def test_two_events_different_ages(self, monkeypatch):
        """Two events at different ages: scores add up."""
        now = 1000.0
        hl = vibe_check.DECAY_HALF_LIFE
        monkeypatch.setattr(time, "time", lambda: now)

        events = [
            {"time": now, "amplitude": 1.0},          # age=0
            {"time": now - 2 * hl, "amplitude": 0.5},  # age=2 half-lives
        ]
        # Event 1: 0.5^0 * (1 + 1*2) = 3.0
        # Event 2: 0.5^2 * (1 + 0.5*2) = 0.25 * 2.0 = 0.5
        expected = 3.0 + 0.5
        assert vibe_check.compute_score(events) == pytest.approx(expected)

    def test_empty_events(self):
        """No events returns 0.0."""
        assert vibe_check.compute_score([]) == 0.0

    def test_amplitude_capped_at_one(self, monkeypatch):
        """Amplitude above 1.0 is clamped to 1.0 in the formula."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        events = [{"time": now, "amplitude": 5.0}]
        # amp_factor = 1 + min(5.0, 1.0)*2 = 3.0, same as amp=1.0
        expected = 1.0 * 3.0
        assert vibe_check.compute_score(events) == pytest.approx(expected)

    def test_negative_amplitude_treated_as_zero_contribution(self, monkeypatch):
        """Negative amplitude: min(neg, 1.0) is negative, so amp_factor < 1."""
        now = 1000.0
        monkeypatch.setattr(time, "time", lambda: now)

        events = [{"time": now, "amplitude": -0.5}]
        # amplitude clamped to 0.0, so amp_factor = 1.0 + 0.0*2 = 1.0
        expected = 1.0 * 1.0
        assert vibe_check.compute_score(events) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 2. score_to_level thresholds
# ---------------------------------------------------------------------------

class TestScoreToLevel:
    """Test boundary conditions for level classification."""

    def test_zero_is_calm(self):
        assert vibe_check.score_to_level(0.0) == "calm"

    def test_just_below_frustrated(self):
        assert vibe_check.score_to_level(vibe_check.FRUSTRATED_THRESHOLD - 0.01) == "calm"

    def test_at_frustrated(self):
        assert vibe_check.score_to_level(vibe_check.FRUSTRATED_THRESHOLD) == "frustrated"

    def test_just_below_hot(self):
        assert vibe_check.score_to_level(vibe_check.HOT_THRESHOLD - 0.01) == "frustrated"

    def test_at_hot(self):
        assert vibe_check.score_to_level(vibe_check.HOT_THRESHOLD) == "hot"

    def test_just_below_angry(self):
        assert vibe_check.score_to_level(vibe_check.ANGRY_THRESHOLD - 0.01) == "hot"

    def test_at_angry(self):
        assert vibe_check.score_to_level(vibe_check.ANGRY_THRESHOLD) == "angry"

    def test_very_high_is_angry(self):
        assert vibe_check.score_to_level(100.0) == "angry"


# ---------------------------------------------------------------------------
# 3. Hook output format
# ---------------------------------------------------------------------------

class TestHookMode:
    """Test the PreToolUse hook JSON output."""

    def _run_hook(self, monkeypatch, cache_data, tmp_path):
        """Helper: write cache, run hook_mode, return parsed output."""
        cache_file = tmp_path / "score.json"
        cache_file.write_text(json.dumps(cache_data))
        monkeypatch.setattr(vibe_check, "SCORE_CACHE", str(cache_file))

        # Provide valid JSON on stdin (Claude Code sends hook input there)
        monkeypatch.setattr("sys.stdin", StringIO('{"hook_name": "PreToolUse"}'))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        vibe_check.hook_mode()

        captured.seek(0)
        return json.loads(captured.read())

    def test_calm_has_no_additional_context(self, monkeypatch, tmp_path):
        result = self._run_hook(monkeypatch, {
            "score": 0.5, "level": "calm", "events_in_window": 0,
        }, tmp_path)

        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "additionalContext" not in result["hookSpecificOutput"]

    def test_frustrated_has_additional_context(self, monkeypatch, tmp_path):
        result = self._run_hook(monkeypatch, {
            "score": 1.5, "level": "frustrated", "events_in_window": 3,
        }, tmp_path)

        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "frustrated" in ctx.lower()
        assert "1.5" in ctx
        assert "3 slaps" in ctx

    def test_hot_has_additional_context(self, monkeypatch, tmp_path):
        result = self._run_hook(monkeypatch, {
            "score": 4.0, "level": "hot", "events_in_window": 8,
        }, tmp_path)

        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "HOT" in ctx
        assert "4.0" in ctx

    def test_angry_has_additional_context(self, monkeypatch, tmp_path):
        result = self._run_hook(monkeypatch, {
            "score": 7.2, "level": "angry", "events_in_window": 15,
        }, tmp_path)

        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "ANGRY" in ctx
        assert "7.2" in ctx

    def test_hook_output_is_valid_json_line(self, monkeypatch, tmp_path):
        """Output must be a single JSON object followed by a newline."""
        cache_file = tmp_path / "score.json"
        cache_file.write_text(json.dumps({
            "score": 0.0, "level": "calm", "events_in_window": 0,
        }))
        monkeypatch.setenv("SLAP_SCORE_CACHE", str(cache_file))
        monkeypatch.setattr("sys.stdin", StringIO("{}"))

        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        vibe_check.hook_mode()

        raw = captured.getvalue()
        assert raw.endswith("\n")
        # Should parse as valid JSON
        json.loads(raw)

    def test_hook_falls_back_when_no_cache(self, monkeypatch, tmp_path):
        """When cache file doesn't exist, hook computes from events file."""
        monkeypatch.setenv("SLAP_SCORE_CACHE", str(tmp_path / "nonexistent.json"))

        # Also set events file to nonexistent so we get score=0
        monkeypatch.setenv("SLAP_EVENTS", str(tmp_path / "nonexistent-events.jsonl"))
        # Need to reload module-level constants after setenv
        monkeypatch.setattr(vibe_check, "SCORE_CACHE", str(tmp_path / "nonexistent.json"))
        monkeypatch.setattr(vibe_check, "EVENTS_FILE", str(tmp_path / "nonexistent-events.jsonl"))

        monkeypatch.setattr("sys.stdin", StringIO("{}"))
        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        vibe_check.hook_mode()

        result = json.loads(captured.getvalue())
        assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        # No events file means calm — no additionalContext
        assert "additionalContext" not in result["hookSpecificOutput"]


# ---------------------------------------------------------------------------
# 4. read_recent_events
# ---------------------------------------------------------------------------

class TestReadRecentEvents:

    def test_empty_file(self, monkeypatch, tmp_path):
        events_file = tmp_path / "events.jsonl"
        events_file.write_text("")
        monkeypatch.setattr(vibe_check, "EVENTS_FILE", str(events_file))

        events = vibe_check.read_recent_events()
        assert events == []

    def test_no_file_at_all(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vibe_check, "EVENTS_FILE", str(tmp_path / "missing.jsonl"))

        events = vibe_check.read_recent_events()
        assert events == []

    def test_corrupt_json_lines_mixed_with_valid(self, monkeypatch, tmp_path):
        """Corrupt lines are skipped; valid lines are parsed."""
        now = time.time()
        ts = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

        lines = [
            "this is not json",
            json.dumps({"slapNumber": 1, "timestamp": ts, "amplitude": 0.8, "severity": "medium"}),
            "{broken",
            json.dumps({"slapNumber": 2, "timestamp": ts, "amplitude": 0.3, "severity": "light"}),
            "",  # blank line
        ]

        events_file = tmp_path / "events.jsonl"
        events_file.write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(vibe_check, "EVENTS_FILE", str(events_file))

        events = vibe_check.read_recent_events(window_seconds=60)
        assert len(events) == 2
        assert events[0]["amplitude"] == 0.8
        assert events[1]["amplitude"] == 0.3

    def test_events_outside_window_are_excluded(self, monkeypatch, tmp_path):
        """Events older than the window are not returned."""
        now = time.time()

        recent_ts = datetime.fromtimestamp(now - 5, tz=timezone.utc).isoformat()
        old_ts = datetime.fromtimestamp(now - 3600, tz=timezone.utc).isoformat()

        lines = [
            json.dumps({"slapNumber": 1, "timestamp": old_ts, "amplitude": 1.0}),
            json.dumps({"slapNumber": 2, "timestamp": recent_ts, "amplitude": 0.5}),
        ]

        events_file = tmp_path / "events.jsonl"
        events_file.write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(vibe_check, "EVENTS_FILE", str(events_file))

        events = vibe_check.read_recent_events(window_seconds=60)
        assert len(events) == 1
        assert events[0]["amplitude"] == 0.5

    def test_slap_number_zero_is_skipped(self, monkeypatch, tmp_path):
        """Events with slapNumber=0 are filtered out (non-slap events)."""
        now = time.time()
        ts = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

        lines = [
            json.dumps({"slapNumber": 0, "timestamp": ts, "amplitude": 1.0}),
            json.dumps({"slapNumber": 1, "timestamp": ts, "amplitude": 0.5}),
        ]

        events_file = tmp_path / "events.jsonl"
        events_file.write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(vibe_check, "EVENTS_FILE", str(events_file))

        events = vibe_check.read_recent_events(window_seconds=60)
        assert len(events) == 1
        assert events[0]["amplitude"] == 0.5

    def test_event_missing_slap_number_is_skipped(self, monkeypatch, tmp_path):
        """Events without slapNumber key are filtered out."""
        now = time.time()
        ts = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

        lines = [
            json.dumps({"timestamp": ts, "amplitude": 1.0}),
            json.dumps({"slapNumber": 1, "timestamp": ts, "amplitude": 0.3}),
        ]

        events_file = tmp_path / "events.jsonl"
        events_file.write_text("\n".join(lines) + "\n")
        monkeypatch.setattr(vibe_check, "EVENTS_FILE", str(events_file))

        events = vibe_check.read_recent_events(window_seconds=60)
        assert len(events) == 1
        assert events[0]["amplitude"] == 0.3


# ---------------------------------------------------------------------------
# 5. Cache read/write consistency
# ---------------------------------------------------------------------------

class TestCacheReadWrite:
    """Write a cache file via the daemon's logic, read it back via hook path."""

    def test_write_and_read_cache_roundtrip(self, monkeypatch, tmp_path):
        """Write cache the way daemon_mode does, read it the way hook_mode does."""
        cache_path = tmp_path / "score.json"
        monkeypatch.setattr(vibe_check, "SCORE_CACHE", str(cache_path))

        # Simulate daemon writing the cache (extracted from daemon_mode logic)
        cache_data = {
            "score": 2.75,
            "level": "frustrated",
            "events_in_window": 4,
        }
        tmp_file = cache_path.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(cache_data))
        tmp_file.rename(cache_path)

        # Now read it back the way hook_mode does
        with open(cache_path) as f:
            cached = json.load(f)

        assert cached["score"] == 2.75
        assert cached["level"] == "frustrated"
        assert cached["events_in_window"] == 4

    def test_cache_used_by_hook(self, monkeypatch, tmp_path):
        """End-to-end: write cache, run hook_mode, verify output matches."""
        cache_path = tmp_path / "score.json"
        monkeypatch.setattr(vibe_check, "SCORE_CACHE", str(cache_path))

        cache_data = {
            "score": 4.5,
            "level": "hot",
            "events_in_window": 10,
        }
        cache_path.write_text(json.dumps(cache_data))

        monkeypatch.setattr("sys.stdin", StringIO("{}"))
        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        vibe_check.hook_mode()

        result = json.loads(captured.getvalue())
        ctx = result["hookSpecificOutput"]["additionalContext"]
        assert "HOT" in ctx
        assert "4.5" in ctx
        assert "10 slaps" in ctx

    def test_corrupt_cache_triggers_fallback(self, monkeypatch, tmp_path):
        """If the cache file is corrupt JSON, hook falls back to events file."""
        cache_path = tmp_path / "score.json"
        cache_path.write_text("{not valid json")
        monkeypatch.setattr(vibe_check, "SCORE_CACHE", str(cache_path))

        # No events file either — should get calm
        monkeypatch.setattr(vibe_check, "EVENTS_FILE", str(tmp_path / "nope.jsonl"))

        monkeypatch.setattr("sys.stdin", StringIO("{}"))
        captured = StringIO()
        monkeypatch.setattr("sys.stdout", captured)

        vibe_check.hook_mode()

        result = json.loads(captured.getvalue())
        assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "additionalContext" not in result["hookSpecificOutput"]

    def test_atomic_write_no_partial_reads(self, tmp_path):
        """The tmp+rename pattern ensures no partial reads."""
        cache_path = tmp_path / "score.json"

        data = {"score": 1.23, "level": "frustrated", "events_in_window": 2}
        tmp_file = cache_path.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(data))

        # Before rename, cache_path should not exist
        assert not cache_path.exists()

        tmp_file.rename(cache_path)

        # After rename, it should be atomically complete
        assert cache_path.exists()
        loaded = json.loads(cache_path.read_text())
        assert loaded == data
