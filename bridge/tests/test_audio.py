from __future__ import annotations

import struct
import sys
import types
import unittest
from unittest.mock import patch

from cardbridge.audio import (
    BLACKHOLE_DEVICE,
    CARDBRIDGE_FEED_DEVICE,
    BlackHoleAudioOutput,
    JitterBuffer,
)


def frame(value: int) -> bytes:
    return struct.pack("<320h", *([value] * 320))


class JitterBufferTests(unittest.TestCase):
    def test_waits_for_target_depth_and_plays_in_sequence(self) -> None:
        jitter = JitterBuffer(target_ms=40)
        jitter.feed(10, frame(10))
        self.assertEqual(jitter.read_samples(320), [0] * 320)
        jitter.feed(11, frame(11))
        self.assertEqual(jitter.read_samples(320), [10] * 320)
        self.assertEqual(jitter.read_samples(320), [11] * 320)

    def test_missing_frame_is_replaced_with_silence(self) -> None:
        jitter = JitterBuffer(target_ms=20)
        jitter.feed(20, frame(20))
        jitter.feed(22, frame(22))
        self.assertEqual(jitter.read_samples(320), [20] * 320)
        self.assertEqual(jitter.read_samples(320), [0] * 320)
        self.assertEqual(jitter.read_samples(320), [22] * 320)
        self.assertEqual(jitter.lost, 1)

    def test_resyncs_after_capture_pause(self) -> None:
        # Mute/reconnect freezes the sender's sequence while playback keeps
        # consuming. The resumed stream must play again instead of being
        # dropped as late forever.
        jitter = JitterBuffer(target_ms=20, max_frames=50)
        jitter.feed(100, frame(1))
        self.assertEqual(jitter.read_samples(320), [1] * 320)
        for _ in range(200):  # 4 s of playback while the sender is paused.
            jitter.read_samples(320)
        jitter.feed(101, frame(2))  # Sender resumes right after its last frame.
        self.assertEqual(jitter.resyncs, 1)
        self.assertEqual(jitter.read_samples(320), [2] * 320)

    def test_starvation_stops_sequence_drift_before_resume(self) -> None:
        jitter = JitterBuffer(target_ms=20, max_frames=50)
        jitter.feed(200, frame(1))
        self.assertEqual(jitter.read_samples(320), [1] * 320)
        for _ in range(jitter.starvation_frames):
            self.assertEqual(jitter.read_samples(320), [0] * 320)
        self.assertEqual(jitter.resyncs, 1)

        # The first resumed frame establishes a fresh stream immediately.
        jitter.feed(201, frame(2))
        self.assertEqual(jitter.read_samples(320), [2] * 320)

    def test_small_reorder_is_still_dropped_as_late(self) -> None:
        jitter = JitterBuffer(target_ms=20, max_frames=50)
        jitter.feed(10, frame(1))
        self.assertEqual(jitter.read_samples(320), [1] * 320)
        jitter.feed(9, frame(9))  # Genuinely late duplicate/reorder.
        self.assertEqual(jitter.late, 1)
        self.assertEqual(jitter.resyncs, 0)


class AudioOutputSelectionTests(unittest.TestCase):
    def _start_with(self, devices: list[dict[str, object]]) -> BlackHoleAudioOutput:
        numpy = types.ModuleType("numpy")
        sounddevice = types.ModuleType("sounddevice")

        class FakeStream:
            def start(self) -> None:
                pass

        sounddevice.query_devices = lambda: devices  # type: ignore[attr-defined]
        sounddevice.OutputStream = lambda **_kwargs: FakeStream()  # type: ignore[attr-defined]
        output = BlackHoleAudioOutput()
        with patch.dict(sys.modules, {"numpy": numpy, "sounddevice": sounddevice}):
            output.start()
        return output

    def test_prefers_bundled_cardbridge_feed(self) -> None:
        output = self._start_with(
            [
                {"name": BLACKHOLE_DEVICE, "max_output_channels": 2, "default_samplerate": 48000},
                {"name": CARDBRIDGE_FEED_DEVICE, "max_output_channels": 2, "default_samplerate": 48000},
            ]
        )
        self.assertEqual(output.device_name, CARDBRIDGE_FEED_DEVICE)

    def test_falls_back_to_existing_blackhole_install(self) -> None:
        output = self._start_with(
            [{"name": BLACKHOLE_DEVICE, "max_output_channels": 2, "default_samplerate": 48000}]
        )
        self.assertEqual(output.device_name, BLACKHOLE_DEVICE)

    def test_restarts_an_inactive_core_audio_stream(self) -> None:
        numpy = types.ModuleType("numpy")
        sounddevice = types.ModuleType("sounddevice")
        streams = []

        class FakeStream:
            def __init__(self) -> None:
                self.active = False
                self.closed = False

            def start(self) -> None:
                self.active = True

            def stop(self) -> None:
                self.active = False

            def close(self) -> None:
                self.closed = True

        def output_stream(**_kwargs: object) -> FakeStream:
            stream = FakeStream()
            streams.append(stream)
            return stream

        sounddevice.query_devices = lambda: [  # type: ignore[attr-defined]
            {
                "name": CARDBRIDGE_FEED_DEVICE,
                "max_output_channels": 2,
                "default_samplerate": 48000,
            }
        ]
        sounddevice.OutputStream = output_stream  # type: ignore[attr-defined]
        output = BlackHoleAudioOutput()
        with patch.dict(sys.modules, {"numpy": numpy, "sounddevice": sounddevice}):
            output.start()
            first = streams[0]
            first.active = False
            output.start()

        self.assertEqual(len(streams), 2)
        self.assertTrue(first.closed)
        self.assertTrue(output.is_running())


if __name__ == "__main__":
    unittest.main()
