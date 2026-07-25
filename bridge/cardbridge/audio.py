from __future__ import annotations

import struct
import threading
from collections import OrderedDict
from typing import Any

from .protocol import AUDIO_SAMPLE_RATE, AUDIO_SAMPLES_PER_FRAME

CARDBRIDGE_FEED_DEVICE = "CardBridge Microphone Feed"
BLACKHOLE_DEVICE = "BlackHole 2ch"


class JitterBuffer:
    """Small sequence-aware PCM jitter buffer with silence loss concealment."""

    def __init__(self, target_ms: int = 100, max_frames: int = 50) -> None:
        self.target_frames = max(1, target_ms // 20)
        self.max_frames = max(max_frames, self.target_frames + 2)
        self.starvation_frames = max(10, self.target_frames * 2)
        self._packets: OrderedDict[int, bytes] = OrderedDict()
        self._samples: list[int] = []
        self._next_sequence: int | None = None
        self._started = False
        self._missing_frames = 0
        self._lock = threading.Lock()
        self.received = 0
        self.lost = 0
        self.late = 0
        self.resyncs = 0

    def feed(self, sequence: int, payload: bytes) -> None:
        with self._lock:
            if self._next_sequence is not None and sequence < self._next_sequence:
                # While capture is paused (mute, reconnect, Mac sleep) playback
                # keeps advancing _next_sequence past the sender's frozen
                # counter. Without a resync every resumed packet would be
                # dropped as late forever.
                if self._next_sequence - sequence > self.max_frames:
                    self._packets.clear()
                    self._samples.clear()
                    self._next_sequence = None
                    self._started = False
                    self._missing_frames = 0
                    self.resyncs += 1
                else:
                    self.late += 1
                    return
            if sequence not in self._packets:
                self._packets[sequence] = payload
                self._packets = OrderedDict(sorted(self._packets.items()))
                self.received += 1
            while len(self._packets) > self.max_frames:
                self._packets.popitem(last=False)

    def _next_frame_locked(self) -> list[int]:
        silence = [0] * AUDIO_SAMPLES_PER_FRAME
        if not self._started:
            if len(self._packets) < self.target_frames:
                return silence
            self._next_sequence = next(iter(self._packets))
            self._started = True

        assert self._next_sequence is not None
        payload = self._packets.pop(self._next_sequence, None)
        self._next_sequence = (self._next_sequence + 1) & 0xFFFFFFFF
        if payload is None:
            self.lost += 1
            self._missing_frames += 1
            if self._missing_frames >= self.starvation_frames:
                # A mode change, WiFi transition, or sleeping Mac can pause
                # capture indefinitely. Stop advancing the expected sequence
                # after a short silence so the next burst starts from a clean
                # jitter depth instead of dragging stale samples into a buzz.
                self._packets.clear()
                self._next_sequence = None
                self._started = False
                self._missing_frames = 0
                self.resyncs += 1
            return silence
        self._missing_frames = 0
        return list(struct.unpack("<320h", payload))

    def read_samples(self, count: int) -> list[int]:
        with self._lock:
            while len(self._samples) < count:
                self._samples.extend(self._next_frame_locked())
            result = self._samples[:count]
            del self._samples[:count]
            return result

    def reset(self) -> None:
        """Drop buffered audio at a deliberate stream/output boundary."""

        with self._lock:
            self._packets.clear()
            self._samples.clear()
            self._next_sequence = None
            self._started = False
            self._missing_frames = 0


class NullAudioOutput:
    def __init__(self, target_ms: int = 100) -> None:
        self.jitter = JitterBuffer(target_ms)

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def is_running(self) -> bool:
        return True

    def feed(self, sequence: int, payload: bytes) -> None:
        self.jitter.feed(sequence, payload)


class BlackHoleAudioOutput(NullAudioOutput):
    def __init__(
        self,
        device_name: str = CARDBRIDGE_FEED_DEVICE,
        target_ms: int = 100,
        gain: float = 20.0,
    ) -> None:
        super().__init__(target_ms)
        self.device_name = device_name
        # Make-up gain. The ES8311 is kept at its clean 0dB setting, where close
        # speech only reaches ~1% full scale; raising the codec's own gain
        # amplified its noise floor faster than the voice. Applying the gain here
        # keeps the codec's SNR and stays tunable without reflashing.
        self.gain = gain
        self._stream: Any = None
        self._numpy: Any = None
        self._source: list[float] = []
        self._phase = 0.0
        self.output_rate = 48_000.0
        self.callback_errors = 0
        self.callback_statuses = 0
        self._callback_failed = False

    def start(self) -> None:
        if self.is_running():
            return
        if self._stream is not None:
            self.stop()
        try:
            import numpy
            import sounddevice
        except ImportError as exc:
            raise RuntimeError(
                "audio dependencies are missing; install bridge/requirements.txt"
            ) from exc
        stream: Any = None
        try:
            devices = sounddevice.query_devices()
            requested_names = [self.device_name]
            # Existing users keep working while the bundled CardBridge driver has
            # not been installed yet. Explicit custom device names do not silently
            # fall back to a different destination.
            if self.device_name == CARDBRIDGE_FEED_DEVICE:
                requested_names.append(BLACKHOLE_DEVICE)
            candidates = []
            for requested_name in requested_names:
                candidates = [
                    (index, device)
                    for index, device in enumerate(devices)
                    if requested_name.lower() in str(device["name"]).lower()
                    and int(device["max_output_channels"]) >= 2
                ]
                if candidates:
                    break
            if not candidates:
                raise RuntimeError(
                    "audio output device was not found; install CardBridge Microphone "
                    f"or {BLACKHOLE_DEVICE}"
                )
            index, device = candidates[0]
            self.device_name = str(device["name"])
            self.output_rate = float(device["default_samplerate"] or 48_000)
            self._numpy = numpy
            stream = sounddevice.OutputStream(
                device=index,
                samplerate=self.output_rate,
                channels=2,
                dtype="float32",
                blocksize=0,
                callback=self._callback,
            )
            stream.start()
            self._stream = stream
            self._callback_failed = False
        except RuntimeError:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            raise
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            raise RuntimeError(f"audio output could not start: {exc}") from exc
        print(f"Audio output: {device['name']} at {self.output_rate:.0f} Hz (software resampling enabled)")

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        self._source.clear()
        self._phase = 0.0
        self.jitter.reset()

    def is_running(self) -> bool:
        if self._stream is None or self._callback_failed:
            return False
        try:
            return bool(self._stream.active)
        except AttributeError:
            # Lightweight test doubles and older sounddevice streams may not
            # expose `active`; a successfully started stream is healthy there.
            return True
        except Exception:
            return False

    def _callback(self, outdata: Any, frames: int, _time: Any, status: Any) -> None:
        if status:
            self.callback_statuses += 1
        try:
            np = self._numpy
            step = AUDIO_SAMPLE_RATE / self.output_rate
            positions = self._phase + np.arange(frames, dtype=np.float64) * step
            required = int(positions[-1]) + 2 if frames else 2
            if len(self._source) < required:
                samples = self.jitter.read_samples(required - len(self._source))
                self._source.extend(sample / 32768.0 for sample in samples)
            mono = np.interp(positions, np.arange(len(self._source)), self._source).astype(np.float32)
            if self.gain != 1.0:
                # tanh soft-clip: loud syllables compress instead of hard-clipping,
                # which would smear the waveform STT depends on.
                mono = np.tanh(mono * self.gain).astype(np.float32)
            outdata[:, 0] = mono
            outdata[:, 1] = mono
            next_position = self._phase + frames * step
            consumed = int(next_position)
            if consumed:
                del self._source[:consumed]
            self._phase = next_position - consumed
        except Exception:
            # PortAudio stops invoking a callback that raises. Fail silent and
            # let the bridge watchdog recreate the stream on its next check.
            self.callback_errors += 1
            self._callback_failed = True
            outdata.fill(0)
