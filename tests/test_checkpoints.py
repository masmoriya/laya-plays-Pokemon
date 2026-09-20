from jpp.checkpoints import CheckpointManager


class FakeEmulator:
    def save_state(self, handle):
        handle.write(b"state")


def test_checkpoints_resume_latest_state_for_one_run(tmp_path):
    manager = CheckpointManager(tmp_path, keep=2)

    manager.save(FakeEmulator(), {"run_id": "run/one"}, "manual")
    latest, _ = manager.save(FakeEmulator(), {"run_id": "run/one"}, "exit")
    manager.save(FakeEmulator(), {"run_id": "run/two"}, "manual")

    assert manager.latest("run/one") == latest
    assert manager.latest("run/two").name.startswith("run-two-")


def test_checkpoint_rotation_does_not_delete_another_run(tmp_path):
    manager = CheckpointManager(tmp_path, keep=1)

    first, _ = manager.save(FakeEmulator(), {"run_id": "alpha"}, "manual")
    other, _ = manager.save(FakeEmulator(), {"run_id": "beta"}, "manual")
    second, _ = manager.save(FakeEmulator(), {"run_id": "alpha"}, "exit")

    assert first.exists()  # manual saves are protected from automatic rotation
    assert other.exists()
    assert second.exists()


def test_resume_can_find_a_legacy_timestamp_checkpoint(tmp_path):
    legacy = tmp_path / "20260920T120000Z-manual.state"
    legacy.write_bytes(b"state")

    assert CheckpointManager(tmp_path).latest("run-001") == legacy


def test_recovery_selects_a_snapshot_not_the_stuck_exit(tmp_path):
    manager = CheckpointManager(tmp_path)
    snapshot, _ = manager.save(FakeEmulator(), {"run_id": "run-001"}, "snapshot")
    manager.save(FakeEmulator(), {"run_id": "run-001"}, "exit")
    manager.save(FakeEmulator(), {"run_id": "run-002"}, "snapshot")

    assert manager.latest_reason("run-001", "snapshot") == snapshot
    assert manager.latest_reason("run-003", "snapshot") is None
