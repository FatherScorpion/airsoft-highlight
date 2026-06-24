"""Detect airsoft 'action/combat' segments in one video via audio analysis.

Combat = dense rapid-fire transients (gunshots) + elevated loudness.
Idle/waiting/plain-walking = quiet, few onsets. Single isolated loud shots
(sniper / shotgun) are recovered via an onset-peak pass.

--min-segments N: ensure at least N segments by progressively LOWERING the
threshold for this video (recall floor — use the round's labeled hit count so a
known-N-hit round yields >=N scenes). The expensive audio analysis runs once;
only the cheap thresholding repeats.

Usage:
    python detect_action.py <video> --out seg.json [--pct 68] [--min-segments 2]
Requires: ffmpeg on PATH, numpy + librosa.
"""
import sys, json, subprocess, argparse
import numpy as np
import librosa

def load_audio(path, sr=11025):
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr),
           "-f", "s16le", "-"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE)
    return np.frombuffer(p.stdout, np.int16).astype(np.float32) / 32768.0, sr

def analyze(path, hop_s=0.25, sr=11025):
    """Expensive part (run once): returns per-frame score, onset, times, dur."""
    y, sr = load_audio(path, sr)
    hop = int(sr * hop_s)
    rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    n = min(len(rms), len(onset))
    rms, onset = rms[:n], onset[:n]
    times = np.arange(n) * hop_s

    def norm(x):
        lo, hi = np.percentile(x, 5), np.percentile(x, 99)
        return np.clip((x - lo) / (hi - lo + 1e-9), 0, 1)

    score = 0.5 * norm(rms) + 0.5 * norm(onset)
    k = max(1, int(1.0 / hop_s))
    score = np.convolve(score, np.ones(k) / k, mode="same")
    onorm = norm(onset)
    dur = float(times[-1]) if n else 0.0
    return score, onset, onorm, times, dur, hop_s

def segment(score, onset, onorm, times, dur, hop_s, pct=68.0,
            merge_gap=2.5, min_len=2.5, pad=1.0, shots=True, shot_pct=97.0):
    """Cheap part: threshold -> merged segments (incl. single-shot peaks)."""
    n = len(score)
    active = score >= np.percentile(score, pct)
    segs, i = [], 0
    while i < n:
        if active[i]:
            j = i
            while j < n and active[j]:
                j += 1
            segs.append([times[i], times[min(j, n - 1)], float(score[i:j].mean())])
            i = j
        else:
            i += 1
    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = s[1]
            merged[-1][2] = max(merged[-1][2], s[2])
        else:
            merged.append(s)
    out = []
    for s, e, sc in merged:
        if e - s < min_len:
            continue
        out.append([round(max(0, s - pad), 2), round(min(dur, e + pad), 2),
                    round(sc, 3)])
    if shots and n:
        thr = np.percentile(onset, shot_pct)
        w = max(1, int(1.5 / hop_s))
        for i in range(n):
            if (onset[i] >= thr and not active[i]
                    and onset[i] == onset[max(0, i - w):i + w + 1].max()):
                out.append([round(max(0, times[i] - 1.5), 2),
                            round(min(dur, times[i] + 2.5), 2),
                            round(float(onorm[i]), 3)])
    out.sort()
    fin = []
    for s, e, sc in out:
        if fin and s <= fin[-1]["end"]:
            fin[-1]["end"] = max(fin[-1]["end"], e)
            fin[-1]["score"] = max(fin[-1]["score"], sc)
        else:
            fin.append({"start": s, "end": e, "score": sc})
    return fin

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out")
    ap.add_argument("--pct", type=float, default=68.0)
    ap.add_argument("--min-segments", type=int, default=0,
                    help="recall floor: lower threshold until >= N segments")
    a = ap.parse_args()

    data = analyze(a.video)
    pct = a.pct
    segs = segment(*data, pct=pct)
    # recall floor: progressively loosen threshold + shot sensitivity
    tries = 0
    while a.min_segments and len(segs) < a.min_segments and pct > 38 and tries < 8:
        pct -= 6
        sp = max(90.0, 97.0 - tries * 1.5)
        segs = segment(*data, pct=pct, shot_pct=sp)
        tries += 1
    dur = data[4]
    total = sum(s["end"] - s["start"] for s in segs)
    res = {"video": a.video, "duration": round(dur, 1), "n_segments": len(segs),
           "action_total": round(total, 1), "pct_used": round(pct, 1),
           "segments": segs}
    if a.out:
        json.dump(res, open(a.out, "w"), indent=2)
    print(json.dumps({k: res[k] for k in
                      ["video", "n_segments", "action_total", "pct_used"]}))
