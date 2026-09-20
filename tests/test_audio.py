from jpp.audio import AudioSink


def test_flush_discards_stale_sound_but_keeps_sink_ready():
    class Channel:
        stopped = False

        def stop(self):
            self.stopped = True

    sink = AudioSink.__new__(AudioSink)
    sink.channel = Channel()
    sink._pending = bytearray(b"old audio")
    sink.enabled = True

    sink.flush()

    assert sink.channel.stopped
    assert not sink._pending
    assert sink.enabled


def test_pump_prebuffers_a_second_chunk_before_starting(monkeypatch):
    class Channel:
        def __init__(self):
            self.played = []

        def get_busy(self):
            return False

        def get_queue(self):
            return None

        def play(self, sound):
            self.played.append(sound)

        def queue(self, sound):
            raise AssertionError("an idle channel should play, not queue")

    sink = AudioSink.__new__(AudioSink)
    sink.channel = Channel()
    sink._chunk_bytes = 4
    sink._start_bytes = 8
    sink._pending = bytearray(b"1234")
    monkeypatch.setattr("jpp.audio.pygame.mixer.Sound", lambda buffer: buffer)

    sink._pump()
    assert sink.channel.played == []

    sink._pending.extend(b"5678")
    sink._pump()
    assert sink.channel.played == [b"1234"]
    assert sink._pending == bytearray(b"5678")


def test_fast_forward_silences_and_flushes_audio():
    class Channel:
        def __init__(self):
            self.stopped = False
            self.volume = None

        def stop(self):
            self.stopped = True

        def set_volume(self, value):
            self.volume = value

    sink = AudioSink.__new__(AudioSink)
    sink.channel = Channel()
    sink._pending = bytearray(b"stale")
    sink._realtime = True
    sink.muted = False

    sink.set_speed(2.0)

    assert not sink._realtime
    assert sink.channel.stopped
    assert not sink._pending
    assert sink.channel.volume == 0.0

    sink.set_speed(1.0)
    assert sink._realtime
    assert sink.channel.volume == 1.0
