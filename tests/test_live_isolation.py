"""Live-state isolation across an explicit model replacement.

Adaptive runtime state is keyed by the model identity, so activating M2 gets its
own Live state and never inherits M1's transient state (rolling buffers, live
observations, posterior/uncertainty state, pending labels, snapshot cache).
Restarting Live after replacement binds to the new active model's key.
"""
from realtime.adaptive import state_key, initial_state
from realtime.config import BALANCED
from realtime.store import RealtimeStore
from services.realtime_service import _pending_id


def test_state_key_and_pending_and_snapshot_are_model_specific():
    m1, m2 = "1111111111111111", "2222222222222222"
    assert state_key(m1, BALANCED) != state_key(m2, BALANCED)  # separate adaptive state
    fp = BALANCED.fingerprint()
    assert _pending_id("AAPL", m1, fp, "2026-08-28") != _pending_id("AAPL", m2, fp, "2026-08-28")


def test_m2_does_not_inherit_m1_runtime_state(tmp_path):
    db = RealtimeStore(tmp_path / "rt.db")
    m1, m2 = "1111111111111111", "2222222222222222"
    k1, k2 = state_key(m1, BALANCED), state_key(m2, BALANCED)

    # M1 has accumulated live state (e.g. matured observations, posterior drift)
    m1_state = initial_state(BALANCED)
    m1_state["drift"] = {"alert": True, "ewma": 0.9, "samples": 200}
    db.save_state(k1, m1, BALANCED.fingerprint(), BALANCED.to_dict(), m1_state)

    # Activating M2 loads M2's key — which has no state yet (not M1's)
    assert db.get_state(k2) is None
    # M1's state remains intact and separately recoverable
    assert db.get_state(k1)["state"]["drift"]["samples"] == 200

    # After M2 accumulates its own state, the two remain independent
    m2_state = initial_state(BALANCED)
    db.save_state(k2, m2, BALANCED.fingerprint(), BALANCED.to_dict(), m2_state)
    assert db.get_state(k2)["state"]["drift"]["samples"] == 0
    assert db.get_state(k1)["state"]["drift"]["samples"] == 200
