"""Extraction de descripteurs musicaux et acoustiques.

Le pipeline est volontairement déterministe et documenté. Il estime des
propriétés perçues (énergie, tension, couleur tonale) et non des émotions
« vraies ». Les features sont calculées sur un WAV normalisé pour limiter les
biais de codec et de mastering.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import librosa
import numpy as np
from scipy.signal import find_peaks

SR = 22050
HOP = 512
N_FFT = 2048

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)


def _f(x, default=0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def _arr(x, n: int | None = None) -> list[float]:
    a = np.asarray(x, dtype=float).ravel()
    if n is not None:
        a = a[:n]
    return [round(_f(v), 6) for v in a]


def _z(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    return (x - np.nanmean(x)) / (np.nanstd(x) + 1e-9)


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def detect_key(chroma: np.ndarray) -> dict:
    mean = chroma.mean(axis=1)
    mean = mean / (mean.sum() + 1e-9)
    scores: list[tuple[float, int, str]] = []
    for root in range(12):
        for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            scores.append((_safe_corr(mean, np.roll(profile, root)), root, mode))
    scores.sort(reverse=True)
    best_corr, root, mode = scores[0]
    second = scores[1][0]
    # La marge entre les deux meilleures corrélations est un indice de fiabilité.
    confidence = float(np.clip(0.30 + 3.2 * (best_corr - second), 0.15, 0.98))
    entropy = float(-np.sum(mean * np.log(mean + 1e-9)) / np.log(12))
    if entropy > 0.96:
        confidence *= 0.65
    return {
        "key": f"{NOTE_NAMES[root]} {mode}",
        "key_root": int(root),
        "mode": mode,
        "key_confidence": round(confidence, 4),
        "key_correlation": round(best_corr, 4),
        "key_margin": round(best_corr - second, 4),
        "chroma_entropy": round(entropy, 4),
        "out_of_key": round(float(np.clip(1.0 - max(best_corr, 0.0), 0.0, 1.0)), 4),
    }


def roughness(freqs: np.ndarray, mag: np.ndarray) -> float:
    """Rugosité de Sethares/Plomp-Levelt sur les pics spectraux.

    Approximation : courbe de dissonance en fonction de l'écart exprimé en ERB.
    Les hautes fréquences et les partiels faibles sont plafonnés pour éviter que
    le bruit large bande ne domine.
    """
    mask = (freqs >= 45.0) & (freqs <= 5200.0)
    f = freqs[mask]
    m = mag[mask]
    if f.size < 4:
        return 0.0
    peaks, _ = find_peaks(np.log(m + 1e-12), prominence=0.18, distance=2)
    if peaks.size < 2:
        return 0.0
    keep = peaks[np.argsort(m[peaks])[-36:]]
    f = f[keep]
    a = m[keep]
    a = a / (a.sum() + 1e-12)
    total = 0.0
    for i in range(len(f)):
        for j in range(i + 1, len(f)):
            fmean = 0.5 * (f[i] + f[j])
            erb = 24.7 * (4.37 * fmean / 1000.0 + 1.0)
            x = abs(f[j] - f[i]) / (erb + 1e-9)
            d = math.exp(-3.5 * x) - 0.5 * math.exp(-5.75 * x)
            total += a[i] * a[j] * max(d, 0.0)
    return float(np.clip(total * 4.2, 0.0, 1.0))


def temporal_arc(rms: np.ndarray, duration: float) -> dict:
    seg = np.array_split(rms, 12)
    means = np.array([float(np.mean(s)) if s.size else 0.0 for s in seg])
    lo, hi = float(np.min(means)), float(np.max(means))
    norm = (means - lo) / (hi - lo + 1e-9)
    n = len(norm)
    peak_idx = int(np.argmax(norm))
    intro_idx = next((i for i, v in enumerate(norm) if v >= 0.5), 0)
    outro_idx = next((i for i in range(n - 1, -1, -1) if norm[i] >= 0.5), n - 1)
    peaks, _ = find_peaks(norm, height=0.55, distance=2)
    if peak_idx >= n - 4:
        kind = "build"
    elif peak_idx <= 3:
        kind = "decay"
    elif len(peaks) >= 3:
        kind = "wave"
    else:
        kind = "steady"
    return {
        "arc": [round(float(v), 4) for v in norm],
        "arc_type": kind,
        "intro_end": round(duration * intro_idx / n, 2),
        "peak_time": round(duration * peak_idx / n, 2),
        "outro_start": round(duration * outro_idx / n, 2),
        "arc_peak_index": peak_idx,
    }


def hook_window(rms: np.ndarray, onset: np.ndarray, duration: float) -> dict:
    n = min(len(rms), len(onset))
    rms = rms[:n]
    onset = onset[:n]
    novelty = _z(rms) + 0.8 * _z(onset)
    win_s = 12.0 if duration >= 24 else max(4.0, duration * 0.25)
    win = max(1, int(win_s * SR / HOP))
    k = np.ones(win) / win
    smooth = np.convolve(novelty, k, mode="same")
    start_min = int(0.10 * n)
    start_max = max(start_min + 1, int(0.85 * n) - win)
    if start_max <= start_min:
        start = 0
    else:
        start = start_min + int(np.argmax(smooth[start_min:start_max]))
    start_s = float(np.clip(start * HOP / SR, 0, max(0, duration - win_s)))
    return {
        "hook_start": round(start_s, 2),
        "hook_duration": round(min(win_s, max(3.0, duration - start_s)), 2),
    }


def cut_points(beat_times: np.ndarray, rms: np.ndarray, duration: float) -> list[float]:
    if duration < 8:
        return []
    candidates = beat_times[::4] if len(beat_times) >= 12 else beat_times
    candidates = np.asarray(
        [t for t in candidates if 0.08 * duration <= t <= 0.92 * duration], dtype=float
    )
    if candidates.size == 0:
        candidates = np.linspace(0.1 * duration, 0.9 * duration, 6)
    targets = np.linspace(0.12, 0.88, 6) * duration
    chosen: list[float] = []
    for target in targets:
        t = float(candidates[np.argmin(np.abs(candidates - target))])
        if all(abs(t - c) >= 2.0 for c in chosen):
            chosen.append(t)
    return [round(t, 2) for t in sorted(chosen)]


def stereo_width(y_stereo: np.ndarray, sr: int) -> float:
    if y_stereo.ndim != 2 or y_stereo.shape[0] < 2:
        return 0.0
    mid = 0.5 * (y_stereo[0] + y_stereo[1])
    side = 0.5 * (y_stereo[0] - y_stereo[1])
    mr = float(np.sqrt(np.mean(mid**2)) + 1e-9)
    srms = float(np.sqrt(np.mean(side**2)) + 1e-9)
    return round(float(np.clip(srms / mr, 0.0, 2.0) / 2.0), 4)


def extract(wav_path: str | Path) -> dict:
    wav_path = Path(wav_path)
    y_stereo, sr = librosa.load(str(wav_path), sr=SR, mono=False)
    if y_stereo.ndim == 1:
        y_stereo = np.vstack([y_stereo, y_stereo])
    y_stereo = y_stereo[:2]
    y = np.mean(y_stereo, axis=0)
    duration = float(librosa.get_duration(y=y, sr=sr))

    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    tempo, beats = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr, hop_length=HOP
    )
    tempo = float(np.asarray(tempo).ravel()[0]) if np.asarray(tempo).size else 0.0
    beat_times = librosa.frames_to_time(beats, sr=sr, hop_length=HOP)
    onsets = librosa.onset.onset_detect(
        onset_envelope=onset_env, sr=sr, hop_length=HOP, backtrack=False
    )
    onset_rate = float(len(onsets) / duration) if duration > 0 else 0.0

    # Clarté de pulse : concentration du tempogramme dans la bande 40–200 BPM.
    tg = np.abs(
        librosa.feature.tempogram(
            onset_envelope=onset_env, sr=sr, hop_length=HOP, win_length=384
        )
    )
    tf = librosa.tempo_frequencies(tg.shape[0], sr=sr, hop_length=HOP)
    band = (tf >= 40) & (tf <= 200)
    profile = tg[band].mean(axis=1) if np.any(band) else np.array([0.0])
    if profile.size and float(profile.max()) > 0:
        peak = float(profile.max())
        mean = float(profile.mean())
        pulse_clarity = float(np.clip((peak - mean) / (peak + 1e-9), 0.0, 1.0))
    else:
        pulse_clarity = 0.0

    rms_curve = librosa.feature.rms(y=y, frame_length=N_FFT, hop_length=HOP)[0]
    rms_db = 20.0 * np.log10(rms_curve + 1e-9)
    rms_mean = float(np.mean(rms_curve))
    crest_db = 20.0 * math.log10((np.max(np.abs(y)) + 1e-9) / (rms_mean + 1e-9))
    dynamic_range = float(np.percentile(rms_db, 95) - np.percentile(rms_db, 10))

    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=N_FFT)
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
    bandwidth = librosa.feature.spectral_bandwidth(S=S, sr=sr)[0]
    rolloff = librosa.feature.spectral_rolloff(S=S, sr=sr, roll_percent=0.85)[0]
    flatness = librosa.feature.spectral_flatness(S=S)[0]
    contrast = librosa.feature.spectral_contrast(S=S, sr=sr)
    zcr = librosa.feature.zero_crossing_rate(y, frame_length=N_FFT, hop_length=HOP)[0]
    flux = np.mean(np.maximum(0.0, np.diff(S, axis=1))) / (
        np.mean(S) + 1e-9
    )
    power = S**2
    total_power = float(np.sum(power) + 1e-9)
    bass_ratio = float(np.sum(power[(freqs >= 20) & (freqs <= 250)]) / total_power)
    mid_ratio = float(np.sum(power[(freqs > 250) & (freqs <= 2000)]) / total_power)
    high_ratio = float(np.sum(power[freqs > 2000]) / total_power)
    avg_mag = np.mean(S, axis=1)
    rough = roughness(freqs, avg_mag)

    mel = librosa.feature.melspectrogram(S=power, sr=sr, n_mels=40)
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(mel), n_mfcc=13)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP)
    chroma_mean = chroma.mean(axis=1)
    chroma_mean = chroma_mean / (chroma_mean.sum() + 1e-9)
    harmonic_entropy = float(
        -np.sum(chroma_mean * np.log(chroma_mean + 1e-9)) / np.log(12)
    )
    key = detect_key(chroma)
    tonnetz = librosa.feature.tonnetz(chroma=chroma)

    y_h, y_p = librosa.effects.hpss(y, margin=3.0)
    e_h = float(np.sum(y_h**2))
    e_p = float(np.sum(y_p**2))
    harmonic_ratio = e_h / (e_h + e_p + 1e-12)
    percussive_ratio = 1.0 - harmonic_ratio

    width = stereo_width(y_stereo, sr)
    arc = temporal_arc(rms_curve, duration)
    hook = hook_window(rms_curve, onset_env, duration)
    cuts = cut_points(beat_times, rms_curve, duration)

    n_loop = max(1, int(5.0 * sr / HOP))
    start_chroma = chroma[:, :n_loop].mean(axis=1)
    end_chroma = chroma[:, -n_loop:].mean(axis=1)
    cos = float(
        np.dot(start_chroma, end_chroma)
        / (np.linalg.norm(start_chroma) * np.linalg.norm(end_chroma) + 1e-9)
    )
    start_rms = float(np.mean(rms_curve[:n_loop]))
    end_rms = float(np.mean(rms_curve[-n_loop:]))
    loopability = float(
        np.clip(
            0.5 * max(0.0, cos)
            + 0.3 * pulse_clarity
            + 0.2 * (1.0 - abs(start_rms - end_rms) / (rms_mean + 1e-9)),
            0.0,
            1.0,
        )
    )

    acousticness = float(
        np.clip(
            0.42 * harmonic_ratio
            + 0.28 * (1.0 - float(np.mean(flatness)))
            + 0.30 * (1.0 - percussive_ratio),
            0.0,
            1.0,
        )
    )
    danceability = float(
        np.clip(
            0.45 * pulse_clarity
            + 0.25 * (1.0 - min(abs(tempo - 110.0) / 80.0, 1.0))
            + 0.20 * min(onset_rate / 4.0, 1.0)
            + 0.10 * harmonic_ratio,
            0.0,
            1.0,
        )
    )
    energy = float(
        np.clip(
            0.28 * min(onset_rate / 3.0, 1.0)
            + 0.24 * min(float(np.mean(centroid)) / 3500.0, 1.0)
            + 0.20 * min(crest_db / 18.0, 1.0)
            + 0.16 * min(flux / 0.8, 1.0)
            + 0.12 * percussive_ratio,
            0.0,
            1.0,
        )
    )

    feats = {
        "analysis_version": "1.1",
        "duration": round(duration, 3),
        "sample_rate": int(sr),
        "tempo": round(tempo, 2),
        "tempo_confidence": round(float(np.clip(pulse_clarity * 1.2, 0, 1)), 4),
        "pulse_clarity": round(pulse_clarity, 4),
        "beat_count": int(len(beat_times)),
        "onset_rate": round(onset_rate, 4),
        "rms_db": round(float(np.mean(rms_db)), 3),
        "dynamic_range_db": round(dynamic_range, 3),
        "crest_db": round(crest_db, 3),
        "spectral_centroid": round(float(np.mean(centroid)), 2),
        "spectral_bandwidth": round(float(np.mean(bandwidth)), 2),
        "spectral_rolloff": round(float(np.mean(rolloff)), 2),
        "spectral_flatness": round(float(np.mean(flatness)), 6),
        "spectral_flux": round(float(flux), 5),
        "zcr": round(float(np.mean(zcr)), 5),
        "spectral_contrast": _arr(np.mean(contrast, axis=1), 7),
        "mfcc_mean": _arr(np.mean(mfcc, axis=1), 13),
        "mfcc_std": _arr(np.std(mfcc, axis=1), 13),
        "chroma_mean": _arr(chroma_mean, 12),
        "tonnetz_mean": _arr(np.mean(tonnetz, axis=1), 6),
        "tonnetz_std": _arr(np.std(tonnetz, axis=1), 6),
        "roughness": round(rough, 4),
        "harmonic_entropy": round(harmonic_entropy, 4),
        "harmonic_ratio": round(harmonic_ratio, 4),
        "percussive_ratio": round(percussive_ratio, 4),
        "bass_ratio": round(bass_ratio, 4),
        "mid_ratio": round(mid_ratio, 4),
        "high_ratio": round(high_ratio, 4),
        "stereo_width": width,
        "acousticness": round(acousticness, 4),
        "danceability": round(danceability, 4),
        "energy": round(energy, 4),
        "loopability": round(loopability, 4),
        "cut_points": cuts,
        **key,
        **arc,
        **hook,
    }
    return feats


if __name__ == "__main__":
    import sys

    print(json.dumps(extract(sys.argv[1]), ensure_ascii=False, indent=2))
