
#!/usr/bin/env python3
"""
Whisper audio transcription with a graphical file picker.

Run the script and select an audio file from the window.
"""

import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import whisper


# ============================ SETTINGS =======================================

WHISPER_MODEL = "small"
LANGUAGE = "en"

# ============================================================================


def pick_audio_file():
    """Open a graphical window to select an audio file."""

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    try:
        audio_path = filedialog.askopenfilename(
            parent=root,
            title="Select audio file for Whisper transcription",
            filetypes=[
                (
                    "Audio files",
                    "*.wav *.mp3 *.ogg *.flac *.m4a *.wma *.aac"
                ),
                ("WAV files", "*.wav"),
                ("MP3 files", "*.mp3"),
                ("OGG files", "*.ogg"),
                ("All files", "*.*"),
            ],
        )
    finally:
        root.destroy()

    return Path(audio_path) if audio_path else None


def main():
    # Add the script's directory to PATH, as in your original code.
    script_directory = Path(__file__).resolve().parent

    os.environ["PATH"] = (
        str(script_directory)
        + os.pathsep
        + os.environ.get("PATH", "")
    )

    # Open the file-selection window.
    audio_path = pick_audio_file()

    if audio_path is None:
        print("No audio file selected. Exiting.")
        return

    if not audio_path.is_file():
        print(f"Audio file was not found: {audio_path}")
        return

    print(f"\nSelected file: {audio_path}")
    print("Loading audio...")

    # Load audio through Whisper to inspect its processed sample count.
    audio = whisper.load_audio(str(audio_path))

    print(f"File: {audio_path.name}")
    print(f"Samples loaded: {len(audio)}")
    print(f"Whisper sample rate: {whisper.audio.SAMPLE_RATE} Hz")
    print(
        "Duration loaded by Whisper: "
        f"{len(audio) / whisper.audio.SAMPLE_RATE:.2f} seconds"
    )

    # Load the Whisper model.
    print(f"\nLoading Whisper model: {WHISPER_MODEL}")
    model = whisper.load_model(WHISPER_MODEL)

    # Transcribe the selected file.
    print("\nStarting transcription...\n")

    result = model.transcribe(
        str(audio_path),
        language=LANGUAGE,
        fp16=False,
        verbose=True,
        condition_on_previous_text=False,
        no_speech_threshold=0.8,
        temperature=(0.0, 0.2, 0.4, 0.6),
    )

    # Print individual segments.
    print("\n--- SEGMENTS ---")

    for segment in result["segments"]:
        print(
            f"{segment['start']:6.2f}–{segment['end']:6.2f} s | "
            f"no-speech={segment['no_speech_prob']:.2f} | "
            f"{segment['text'].strip()}"
        )

    # Print the complete transcript.
    print("\n--- FULL TRANSCRIPT ---")
    print(result["text"].strip())


if __name__ == "__main__":
    main()
