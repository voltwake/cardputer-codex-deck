from __future__ import annotations

import struct
import sys
import threading
import types
import unittest
from unittest.mock import patch

import numpy

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

    def test_reset_stream_clears_resampler_boundary_and_jitter(self) -> None:
        output = BlackHoleAudioOutput()
        output._source.extend([0.25, -0.25])
        output._phase = 0.75
        output.jitter.feed(10, frame(99))

        output.reset_stream()

        self.assertEqual(output._source, [])
        self.assertEqual(output._phase, 0.0)
        self.assertEqual(output.jitter.read_samples(320), [0] * 320)

    def test_reset_stream_waits_for_an_active_audio_callback(self) -> None:
        callback_entered = threading.Event()
        release_callback = threading.Event()
        reset_started = threading.Event()
        reset_finished = threading.Event()

        class BlockingJitter:
            reset_called = False

            def read_samples(self, count: int) -> list[int]:
                callback_entered.set()
                self.assert_released()
                return [1024] * count

            def assert_released(self) -> None:
                if not release_callback.wait(1):
                    raise AssertionError("audio callback was not released")

            def reset(self) -> None:
                self.reset_called = True

        output = BlackHoleAudioOutput(gain=1.0)
        output._numpy = numpy
        output.jitter = BlockingJitter()  # type: ignore[assignment]
        outdata = numpy.zeros((64, 2), dtype=numpy.float32)

        callback_thread = threading.Thread(
            target=output._callback,
            args=(outdata, 64, None, None),
        )

        def reset() -> None:
            reset_started.set()
            output.reset_stream()
            reset_finished.set()

        callback_thread.start()
        self.assertTrue(callback_entered.wait(1))
        reset_thread = threading.Thread(target=reset)
        reset_thread.start()
        self.assertTrue(reset_started.wait(1))
        self.assertFalse(reset_finished.wait(0.05))
        release_callback.set()
        callback_thread.join(1)
        reset_thread.join(1)

        self.assertFalse(callback_thread.is_alive())
        self.assertFalse(reset_thread.is_alive())
        self.assertTrue(output.jitter.reset_called)
        self.assertEqual(output.callback_errors, 0)
        self.assertEqual(output._source, [])
        self.assertEqual(output._phase, 0.0)


if __name__ == "__main__":
    unittest.main()
