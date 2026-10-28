#!/usr/bin/env python3
"""Estimate SNR for laser-microphone data captured by an ESP32 ADC.

No terminal needed: edit the SETTINGS block below, then press Run in your editor
(Spyder, VS Code, Thonny, IDLE...). If DATA_FILE is None, a file-picker window
opens so you can choose the file.

Accepted inputs:
  .csv / .txt : one column of raw ADC codes (set SAMPLE_RATE_HZ), OR two
                columns (time, code); time unit is auto-detected.
  .wav        : already-converted audio.

Install: pip install numpy scipy matplotlib soundfile
"""
# ============================ SETTINGS (edit me) ============================
DATA_FILE = None            # e.g. r"C:\Users\you\Desktop\speech.csv"; None = pick with a dialog
NOISE_FILE = None           # path to a noise-only recording; None = estimate from quiet frames;
                            # "ASK" = open a second file dialog
SAMPLE_RATE_HZ = 8000       # needed for single-column CSV; None = use timestamps
ADC_BITS = 12               # ESP32 ADC resolution
BAND_HZ = (100.0, 3400.0)   # analysis band (low, high)
MAINS_HZ = 50               # mains hum notch (50 for South Africa, 0 = off)
FRAME_MS = 25.0
HOP_MS = 10.0
SHOW_PLOT = True
# ============================================================================

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, sosfiltfilt, iirnotch, filtfilt, resample_poly, welch


def load_data(path, fs_arg, adc_bits):
    """Return (signal scaled to full-scale, fs, raw ADC codes or None)."""
    p = Path(path)
    if p.suffix.lower() == ".wav":
        import soundfile as sf
        a, fs = sf.read(p, dtype="float64", always_2d=True)
        return a.mean(axis=1), fs, None

    raw = np.genfromtxt(p, delimiter=",", comments="#")
    raw = raw[~np.isnan(raw).any(axis=-1)] if raw.ndim > 1 else raw[~np.isnan(raw)]
    if raw.ndim == 1:
        if fs_arg is None:
            raise ValueError("Single-column file: set SAMPLE_RATE_HZ.")
        codes, fs = raw.astype(float), float(fs_arg)
    else:
        t, codes = raw[:, 0].astype(float), raw[:, 1].astype(float)
        dt = np.median(np.diff(t))
        if dt <= 0:
            raise ValueError("Time column is not increasing.")
        scale = 1.0 if dt < 0.1 else (1e-3 if dt < 100 else 1e-6)  # s, ms or us
        t = t * scale
        fs_est = 1.0 / np.median(np.diff(t))
        fs = float(fs_arg) if fs_arg else fs_est
        gaps = np.diff(t) > 1.5 * np.median(np.diff(t))
        print(f"Timestamp-estimated fs: {fs_est:.1f} Hz | gaps (dropped samples): "
              f"{int(gaps.sum())} ({100*gaps.mean():.3f}%)")
        tu = np.arange(t[0], t[-1], 1.0 / fs)      # uniform grid for valid filtering
        codes = np.interp(tu, t, codes)
    return codes / (2 ** adc_bits - 1), fs, codes


def band_filter(x, fs, lo, hi, mains):
    hi = min(hi, 0.45 * fs)
    sos = butter(4, [lo, hi], btype="bandpass", fs=fs, output="sos")
    y = sosfiltfilt(sos, x)
    if mains:
        for k in (1, 2, 3):
            f0 = mains * k
            if f0 < 0.45 * fs:
                b, a = iirnotch(f0, Q=30, fs=fs)
                y = filtfilt(b, a, y)
    return y


def frame_rms(x, fs, frame_ms, hop_ms):
    fl, hl = max(1, int(fs * frame_ms / 1e3)), max(1, int(fs * hop_ms / 1e3))
    if len(x) < fl:
        x = np.pad(x, (0, fl - len(x)))
    starts = np.arange(0, len(x) - fl + 1, hl)
    lev = np.array([np.sqrt(np.mean(x[s:s + fl] ** 2)) for s in starts])
    return lev, (starts + fl / 2) / fs


def analyse(args):
    x, fs, codes = load_data(args.file, args.fs, args.adc_bits)
    print(f"\nFile: {Path(args.file).resolve()}\nSample rate: {fs:.1f} Hz | Duration: {len(x)/fs:.2f} s")

    if codes is not None:
        top = 2 ** args.adc_bits - 1
        at_rail = np.mean((codes <= 2) | (codes >= top - 2)) * 100
        p2p = codes.max() - codes.min()
        print(f"ADC codes: min {codes.min():.0f}, max {codes.max():.0f}, "
              f"mean {codes.mean():.0f} ({100*codes.mean()/top:.1f}% of range)")
        print(f"Used {p2p:.0f} of {top} codes ({100*p2p/top:.1f}%) | samples at rail: {at_rail:.3f}%")
        if at_rail > 0.01:
            print("WARNING: ADC saturating - reduce gain or the clamp is being hit.")
        if p2p < 0.05 * top:
            print("NOTE: signal uses <5% of ADC range - quantisation noise may limit SNR.")

    x = x - np.mean(x)
    y = band_filter(x, fs, args.band[0], args.band[1], args.mains)
    lev, times = frame_rms(y, fs, args.frame_ms, args.hop_ms)
    if len(lev) < 8:
        raise ValueError("Recording too short for a stable estimate.")

    if args.noise_file:
        xn, fsn, _ = load_data(args.noise_file, args.fs, args.adc_bits)
        if abs(fsn - fs) > 1:
            xn = resample_poly(xn, int(round(fs)), int(round(fsn)))
        xn = band_filter(xn - np.mean(xn), fs, args.band[0], args.band[1], args.mains)
        noise_power = float(np.mean(xn ** 2))
        method = "separate noise-only recording"
    else:
        quiet = lev <= np.percentile(lev, 25)
        noise_power = float(np.mean(lev[quiet] ** 2))
        method = "quietest 25% of frames (heuristic)"
    thr = max(np.sqrt(noise_power) * 10 ** (6 / 20), np.percentile(lev, 50))

    speech = lev > thr
    fb = False
    if np.count_nonzero(speech) < max(3, int(0.05 * len(lev))):
        thr, fb = np.percentile(lev, 60), True
        speech = lev >= thr
    if np.count_nonzero(speech) < 2:
        raise ValueError("Could not find enough likely speech frames.")

    sp_pow = float(np.mean(lev[speech] ** 2)) - noise_power
    snr = 10 * np.log10(sp_pow / noise_power) if sp_pow > 0 else float("nan")
    n_rms = np.sqrt(noise_power)

    print(f"\n===== Laser mic SNR ({args.band[0]:.0f}-{min(args.band[1],0.45*fs):.0f} Hz band) =====")
    print(f"Noise reference: {method}")
    print(f"Noise RMS : {n_rms:.3e} FS  ({20*np.log10(max(n_rms,1e-15)):.1f} dBFS)")
    if sp_pow > 0:
        print(f"Speech RMS: {np.sqrt(sp_pow):.3e} FS  ({10*np.log10(sp_pow):.1f} dBFS)")
    print(f"Estimated SNR: {snr:.2f} dB")
    print(f"Speech frames: {np.count_nonzero(speech)}/{len(lev)}")
    if codes is not None:
        print(f"Noise RMS in ADC LSBs: {n_rms*(2**args.adc_bits-1):.2f}  (~0.3 LSB is the quantisation floor)")
    if fb:
        print("WARNING: fallback speech threshold used.")
    if not np.isfinite(snr):
        print("WARNING: no positive speech-only power found.")

    if not args.no_plot:
        fig, ax = plt.subplots(3, 1, figsize=(12, 9), constrained_layout=True)
        t = np.arange(len(x)) / fs
        ax[0].plot(t, y, lw=0.5); ax[0].set(title="Band-passed laser mic signal", xlabel="Time (s)", ylabel="FS")
        db = 20 * np.log10(np.maximum(lev, 1e-12))
        ax[1].plot(times, db, label="Frame RMS")
        ax[1].axhline(20 * np.log10(max(n_rms, 1e-12)), ls="--", label="Noise floor")
        ax[1].axhline(20 * np.log10(max(thr, 1e-12)), ls=":", label="Speech threshold")
        ax[1].fill_between(times, db, db.min(), where=speech, alpha=0.2, label="Speech frames")
        ax[1].set(title="Frame energy", xlabel="Time (s)", ylabel="dBFS"); ax[1].legend()
        f, P = welch(x, fs, nperseg=min(4096, len(x)))
        ax[2].semilogy(f, P)
        ax[2].set(title="Power spectrum (look for hum / laser noise peaks)", xlabel="Hz", ylabel="PSD")
        for a in ax:
            a.grid(True, alpha=0.3)
        plt.show()
    return snr


def pick_file(title):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title=title, filetypes=[("Data files", "*.csv *.txt *.wav"), ("All files", "*.*")])
    root.destroy()
    return path or None


def main():
    data_file = DATA_FILE or pick_file("Select laser mic recording")
    if not data_file:
        print("No file selected.")
        return
    noise_file = pick_file("Select noise-only recording") if NOISE_FILE == "ASK" else NOISE_FILE
    args = SimpleNamespace(
        file=data_file, fs=SAMPLE_RATE_HZ, adc_bits=ADC_BITS, band=list(BAND_HZ),
        mains=MAINS_HZ, noise_file=noise_file, frame_ms=FRAME_MS, hop_ms=HOP_MS,
        no_plot=not SHOW_PLOT)
    try:
        analyse(args)
    except (OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
