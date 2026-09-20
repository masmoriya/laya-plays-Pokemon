from jpp import frame_pacer


def test_frame_deadline_includes_work_done_after_emulator_tick(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(frame_pacer.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(frame_pacer.time, "sleep", lambda duration: now.__setitem__(0, now[0] + duration))
    pacer = frame_pacer.FramePacer()

    now[0] = 0.005  # emulator and UI work have already taken 5 ms
    pacer.wait(1)
    assert abs(now[0] - 1 / frame_pacer.GAME_FRAMES_PER_SECOND) < 0.00001

    now[0] += 0.030  # an over-budget frame must not wait again
    pacer.wait(1)
    assert now[0] < 0.050
