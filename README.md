# Laser-Based Listening Device — EEE4022S

Final-year engineering project by **Colby Skirving (SKRCOL001)**  
Department of Electrical Engineering, University of Cape Town  
Supervisor: Dr S. Paine  
October 2026

## Overview

This project investigates whether a low-cost, intensity-modulated laser listening device can recover speech from a vibrating glass target with sufficient quality for automatic transcription.

A laser beam is reflected from the target onto a BPW34 photodiode. Changes in the collected light generate a photocurrent, which is converted into a voltage by two opposite-polarity transimpedance amplifier (TIA) channels. A difference amplifier combines the channels, and an ESP32 digitises the conditioned signal.

The sampled audio is transmitted over USB serial to a computer, saved as a WAV file, processed in Audacity, and evaluated using estimated signal-to-noise ratio (SNR) and word error rate (WER).

The project is a controlled laboratory demonstrator. It was not evaluated as a field-deployable surveillance system.

## System Architecture

```text
Known audio played through a speaker
                 |
                 v
        Vibrating glass target
                 ^
                 |
        Incident laser beam
                 |
                 v
        Reflected laser light
                 |
                 v
         BPW34 photodiode
                 |
                 v
    Opposite-polarity dual TIA channels
                 |
                 v
       AC-coupled difference amplifier
                 |
                 v
       ESP32 ADC sampling at 30 kHz
                 |
                 v
         Binary USB serial stream
                 |
                 v
        Python recorder → WAV file
                 |
                 v
      Audacity filtering and noise reduction
                 |
                 v
        SNR estimation and Whisper transcription
                 |
                 v
        WER comparison against reference text
```

## Hardware

The principal hardware components are:

- One BPW34 silicon PIN photodiode.
- Two LM358 dual operational-amplifier packages.
- An ESP32 development board.
- A visible red laser module, nominally 650 nm and up to 5 mW.
- A resistor-divider reference with a nominal voltage of 1.65 V.
- Resistors and capacitors for amplification, AC coupling and decoupling.
- A custom 3D-printed receiver enclosure and optical baffle.
- A laser mount and receiver height adjuster.
- A glass-fronted target enclosure containing the test speaker.
- A disassembled G63 Bluetooth speaker used as the controlled audio source.

### Analogue Receiver

A single photodiode connects to two TIA channels whose outputs move in opposite directions in response to photocurrent. The difference-amplifier stage combines these signals.

Ambient illumination entering through the same photodiode is not independently cancelled by this topology. Ambient-light management relies on mechanical shielding, appropriate analogue operating conditions and AC coupling.

### Manufacturing Status

All reported experimental results were obtained using the veroboard prototype.

A custom two-layer PCB layout is included as a proposed implementation. It was not fabricated or bench-tested during the project. PCB files should therefore not be interpreted as evidence of measured PCB performance.

## Repository Contents

The main software files referenced in the report are:

| File | Purpose |
|---|---|
| `SpeechSamplingV1.ino` | ESP32 ADC acquisition and binary serial transmission |
| `esp32_recorder.py` | Serial decoding, audio conditioning and WAV recording |
| `laser_mic_snr_gui.py` | Estimated SNR analysis of recorded audio |
| `whisperTest.py` | Speech transcription using OpenAI Whisper |

## Software Environment

For Whisper installation and its audio-decoding prerequisites, follow the official instructions:

https://github.com/openai/whisper

### Firmware

1. Open `SpeechSamplingV1.ino` in the Arduino IDE.
2. Select the exact ESP32 board used for the project.
3. Confirm the ADC input, sample rate, packet size and serial baud rate.
4. Select the correct serial port.
5. Compile and upload the firmware.
6. Close the Arduino Serial Monitor before opening the Python recorder.

Record the board support package version used for a successful build.

## Recording Audio

### Recorder Configuration

Open `esp32_recorder.py` and check the following settings:

```python
SERIAL_PORT = "COM4"
SERIAL_BAUD = 921600

SAMPLE_RATE = 30000
SAMPLES_PER_PACKET = 256

PLAY_AUDIO = False
RECORD_AUDIO = True

OUTPUT_GAIN = 1

BASELINE_COUNTS =  2034 
```

The serial port must be changed to match the connected device.

The sample rate and packet size must agree with the firmware. The baseline value must match the actual recorder version used to acquire each dataset.

### Recording Procedure

1. Connect the receiver output to the configured ESP32 ADC input.
2. Confirm the receiver and ESP32 share the required ground reference.
3. Check the analogue signal remains within the ADC's valid input range.
4. Align the laser, glass target and receiver.
5. Close any other application using the serial port.
6. Run: python esp32_recorder.py
7. Press Enter when prompted.
8. Wait for the recording countdown.
9. Play the selected test audio.
10. Press `Ctrl+C` to stop.
11. Retain the saved WAV file and the acquisition statistics.

## Binary Serial Protocol

Each packet contains an 8-byte header followed by the sample payload.

| Field | Size | Description |
|---|---:|---|
| Sync marker | 2 bytes | `0xAA 0x55` |
| Sequence number | 4 bytes | Unsigned little-endian packet counter |
| Sample count | 2 bytes | Unsigned little-endian count; normally 256 |
| Payload | 512 bytes | 256 samples stored as little-endian unsigned 16-bit values |

The receiver extracts the 12-bit ADC code from each sample.

## Audacity Post-Processing

Audio enhancement was performed manually in Audacity, rather than by the recording script.

The reported effect settings were:

| Effect | Setting |
|---|---|
| Amplification | +20 dB |
| Noise reduction | 16 dB |
| Noise-reduction sensitivity | 5.01 |
| Frequency smoothing | 6 bands |
| Low-pass cutoff | 3000 Hz |
| Low-pass slope | 48 dB/octave |

A noise profile was obtained from a speech-free portion of the recording.

## SNR Estimation

Use the SNR analysis script included in the repository.

The report describes a frame-energy method using:

- A speech-oriented analysis band, nominally 100–3400 Hz.
- Frames of 25 ms.
- The quietest 25% of frames to estimate the noise floor.
- A speech threshold 6 dB above the estimated noise floor.

## Whisper Transcription

The report uses OpenAI Whisper with the `small` model.

The documented settings are:

```python
language="en"
fp16=False
condition_on_previous_text=False
```

Run `whisperTest.py` using the input-file configuration .


## Word Error Rate

WER compares the generated transcript with a fixed reference transcript:

```text
WER = (substitutions + deletions + insertions) / reference word count
```

Multiply by 100 to express WER as a percentage.

## Limitations

- Testing was performed in a controlled laboratory.
- Evaluation used a fixed 1 m optical distance and one target arrangement.
- Speech evaluation used a limited passage and set of test conditions.
- Optical alignment was manual
- Packet loss occurred during some recordings.
- The custom PCB was not fabricated or bench-tested.
- The effect of different speakers, rooms, target materials and longer optical ranges was not established.

## Safety and Ethical Use

This repository documents a controlled academic experiment using known audio played through a laboratory speaker.

The source is a visible laser module rated up to 5 mW. Follow the applicable laser-safety procedures and the module's safety classification. Avoid direct or reflected exposure to eyes and prevent the beam from entering uncontrolled areas.

Do not use the system to record private conversations or conduct monitoring without the required permission, consent and institutional approval.

## Third-Party Material and Attribution

The receiver enclosure and baffle were designed for this project.

The report attributes the laser holder and height-adjuster models to third-party Printables designs. 

Reference audio was obtained from LibriVox. 

## Author

Colby Skirving  
Student number: SKRCOL001  
BSc Electrical and Computer Engineering  
University of Cape Town
