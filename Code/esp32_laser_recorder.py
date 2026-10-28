import os
import struct
import time
import wave

import numpy as np
import serial
from scipy import signal


# ============================================================
# USER SETTINGS
# ============================================================

SERIAL_PORT = "COM4"
SERIAL_BAUD = 921600

SAMPLE_RATE = 30000
SAMPLES_PER_PACKET = 256

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_LASER_WAV = os.path.join(
    SCRIPT_DIR, "esp32_optical_audio.wav"
)

# Enable only when monitoring with headphones.
PLAY_AUDIO = False
RECORD_AUDIO = True

# No additional amplification during acquisition.
# The 20 dB amplification is applied separately in Audacity.
OUTPUT_GAIN = 1.0

# Second-order high-pass filter used during acquisition.
HIGH_PASS_HZ = 300.0

# Measured virtual-ground voltage: 1.639 V.
# (1.639 / 3.3) * 4095 ≈ 2034 ADC counts.
BASELINE_COUNTS = 2034


# ============================================================
# BINARY PROTOCOL CONSTANTS
# ============================================================

# Full header:
#   sync marker:  2 bytes (0xAA 0x55)
#   sequence:     4 bytes, little-endian uint32
#   sample_count: 2 bytes, little-endian uint16
HEADER_REMAINDER_SIZE = 6


# ============================================================
# DIGITAL FILTER SETUP
# ============================================================

nyquist = SAMPLE_RATE / 2.0

if not 0 < HIGH_PASS_HZ < nyquist:
    raise ValueError(
        f"HIGH_PASS_HZ must be between 0 and {nyquist} Hz."
    )

hp_sos = signal.butter(
    2,
    HIGH_PASS_HZ,
    btype="highpass",
    fs=SAMPLE_RATE,
    output="sos",
)

hp_state = np.zeros(
    (hp_sos.shape[0], 2),
    dtype=np.float64,
)

recorded_blocks = []


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def find_serial_sync(ser):
    """Scan for the 0xAA 0x55 packet marker."""
    previous = None

    while True:
        current = ser.read(1)

        if not current:
            return False

        if previous == b"\xAA" and current == b"\x55":
            return True

        previous = current


def read_exact(ser, byte_count):
    """Read the requested number of bytes, or return None on timeout."""
    data = bytearray()

    while len(data) < byte_count:
        chunk = ser.read(byte_count - len(data))

        if not chunk:
            return None

        data.extend(chunk)

    return bytes(data)


def adc_to_audio(adc_codes):
    """Subtract the baseline, high-pass filter, and scale the audio."""
    global hp_state

    audio = adc_codes.astype(np.float64)

    audio = (audio - BASELINE_COUNTS) / BASELINE_COUNTS

    audio, hp_state = signal.sosfilt(
        hp_sos,
        audio,
        zi=hp_state,
    )

    audio *= OUTPUT_GAIN

    return np.clip(audio, -1.0, 1.0).astype(np.float32)


def save_wav(filename, audio_blocks, sample_rate):
    """Save recorded audio as a mono, 16-bit PCM WAV file."""
    if not audio_blocks:
        print(
            f"No audio captured for {filename}; "
            "WAV file not created."
        )
        return None

    audio = np.concatenate(audio_blocks)

    pcm16 = np.clip(
        audio * 32767.0,
        -32768,
        32767,
    ).astype("<i2")

    with wave.open(filename, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm16.tobytes())

    duration = len(audio) / sample_rate

    print(
        f"Saved: {filename}\n"
        f"Duration: {duration:.2f} s | "
        f"Samples: {len(audio)} | "
        f"Sample rate: {sample_rate} Hz"
    )

    return audio


# ============================================================
# RECORDING LOOP
# ============================================================

def record_from_esp32():
    global hp_state

    packet_count = 0
    dropped_packets = 0
    malformed_packets = 0
    last_sequence = None
    start_time = None
    out_stream = None

    recorded_blocks.clear()
    hp_state = np.zeros(
        (hp_sos.shape[0], 2),
        dtype=np.float64,
    )

    ser = serial.Serial(
        port=SERIAL_PORT,
        baudrate=SERIAL_BAUD,
        timeout=1.0,
    )

    try:
        time.sleep(1.0)
        ser.reset_input_buffer()

        if PLAY_AUDIO:
            import sounddevice as sd

            out_stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=SAMPLES_PER_PACKET,
                latency="low",
            )
            out_stream.start()

        print("[ESP32] Connected and ready.")
        input(
            "Press Enter to begin recording "
            "(Ctrl+C to stop)..."
        )

        print("\nStarting recording in 3...")
        time.sleep(1)
        print("2...")
        time.sleep(1)
        print("1...")
        time.sleep(1)

        ser.reset_input_buffer()
        start_time = time.perf_counter()

        print("\nRecording. Press Ctrl+C to stop.\n")

        while True:
            if not find_serial_sync(ser):
                continue

            header = read_exact(
                ser,
                HEADER_REMAINDER_SIZE,
            )

            if header is None:
                malformed_packets += 1
                continue

            sequence, sample_count = struct.unpack(
                "<IH",
                header,
            )

            if sample_count != SAMPLES_PER_PACKET:
                malformed_packets += 1
                continue

            payload = read_exact(
                ser,
                sample_count * 2,
            )

            if payload is None:
                malformed_packets += 1
                continue

            adc_codes = (
                np.frombuffer(payload, dtype="<u2")
                & 0x0FFF
            )

            if len(adc_codes) != SAMPLES_PER_PACKET:
                malformed_packets += 1
                continue

            if last_sequence is not None:
                expected_sequence = (
                    last_sequence + 1
                ) & 0xFFFFFFFF

                if sequence != expected_sequence:
                    sequence_gap = (
                        sequence - expected_sequence
                    ) & 0xFFFFFFFF

                    if sequence_gap < 0x80000000:
                        missing = sequence_gap
                        dropped_packets += missing

                        # Insert silence for missing packets to
                        # preserve the recording timebase.
                        for _ in range(missing):
                            silence = np.zeros(
                                SAMPLES_PER_PACKET,
                                dtype=np.float32,
                            )

                            if PLAY_AUDIO:
                                out_stream.write(
                                    silence.reshape(-1, 1)
                                )

                            if RECORD_AUDIO:
                                recorded_blocks.append(silence)

                        # Discard filter history across the gap.
                        hp_state.fill(0.0)

                    else:
                        print(
                            "[ESP32] Warning: sequence "
                            "reset/reordered "
                            f"({last_sequence} -> {sequence})"
                        )
                        hp_state.fill(0.0)

            last_sequence = sequence

            audio = adc_to_audio(adc_codes)

            if PLAY_AUDIO:
                out_stream.write(audio.reshape(-1, 1))

            if RECORD_AUDIO:
                recorded_blocks.append(audio.copy())

            packet_count += 1

            if packet_count % 100 == 0:
                print(
                    f"[ESP32] Packets: {packet_count:6d} | "
                    f"Raw min/max: "
                    f"{int(adc_codes.min()):4d}/"
                    f"{int(adc_codes.max()):4d} | "
                    f"Mean: {float(adc_codes.mean()):7.1f} | "
                    f"Dropped: {dropped_packets:4d} | "
                    f"Malformed: {malformed_packets:3d}"
                )

    except KeyboardInterrupt:
        print("\nStopping recording...")

    finally:
        # Capture elapsed time before closing the audio stream.
        elapsed = (
            time.perf_counter() - start_time
            if start_time is not None
            else 0.0
        )

        try:
            if out_stream is not None:
                try:
                    out_stream.stop()
                finally:
                    out_stream.close()
        finally:
            ser.close()

        received_samples = (
            packet_count * SAMPLES_PER_PACKET
        )

        missing_samples = (
            dropped_packets * SAMPLES_PER_PACKET
        )

        timeline_samples = (
            received_samples + missing_samples
        )

        print(
            f"[ESP32] Stopped. "
            f"Packets: {packet_count}, "
            f"Dropped: {dropped_packets}, "
            f"Malformed: {malformed_packets}"
        )

        if elapsed > 0 and packet_count > 0:
            # Host-side throughput estimate, not a direct
            # measurement of the ADC sampling clock.
            effective_rate = received_samples / elapsed

            rate_error = 100.0 * (
                effective_rate / SAMPLE_RATE - 1.0
            )

            loss_percent = (
                100.0 * missing_samples / timeline_samples
                if timeline_samples > 0
                else 0.0
            )

            print(
                "[ESP32] Effective received sample rate: "
                f"{effective_rate:.0f} Hz "
                f"(nominal {SAMPLE_RATE} Hz, "
                f"error {rate_error:+.2f}%)"
            )

            print(
                "[ESP32] Samples replaced with silence: "
                f"{missing_samples} "
                f"({loss_percent:.4f}% of timeline)"
            )

            print(
                "[ESP32] Recording timeline: "
                f"{timeline_samples / SAMPLE_RATE:.2f} s"
            )


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():
    print("=" * 70)
    print("ESP32 Laser Microphone Recorder")
    print("=" * 70)

    print(
        f"Sample rate:   {SAMPLE_RATE} Hz "
        f"(via {SERIAL_PORT} @ {SERIAL_BAUD} baud)"
    )
    print(
        f"ADC baseline:  {BASELINE_COUNTS} counts "
        "(measured Vref = 1.639 V)"
    )
    print(
        f"Live filter:   second-order "
        f"{HIGH_PASS_HZ:.0f} Hz high-pass"
    )
    print("Live notch:    OFF")
    print("Live low-pass: OFF")
    print(f"Output gain:   {OUTPUT_GAIN:.1f}")

    print(
        f"Live playback: "
        f"{'ON' if PLAY_AUDIO else 'OFF'}"
    )
    print(
        f"WAV recording: "
        f"{'ON' if RECORD_AUDIO else 'OFF'}"
    )

    print()
    print("Post-processing is performed separately in Audacity:")
    print("  Amplification:   20 dB")
    print("  Noise reduction: 16 dB")
    print("  Sensitivity:     5.01")
    print("  Smoothing:       6 bands")
    print("  Low-pass:        3000 Hz, 48 dB/octave")
    print()
    print(
        "Close the Arduino Serial Monitor "
        "before running this script."
    )
    print()

    try:
        record_from_esp32()
    finally:
        if RECORD_AUDIO:
            save_wav(
                OUTPUT_LASER_WAV,
                recorded_blocks,
                SAMPLE_RATE,
            )


if __name__ == "__main__":
    main()