"""Detect the player's KILL callouts from Scribe transcripts.

Scribe tokenizes Japanese per character, so we concatenate word tokens into
one string while keeping a char->(time, speaker) map, then regex-search for
kill announcements. The kill happens just BEFORE the shout, so we build a
clip window [t-pre, t+post] around each callout and merge nearby ones.

Usage:
    python detect_kills.py --work <edit_dir>
Reads  <edit_dir>/transcripts/*.json
Writes <edit_dir>/kills.json -> [{file,start,end,t,phrases:[..],speaker}, ...]

Tune PATTERNS to the player's habits. Common JP airsoft kill calls:
  'Nダウン', 'やった', 'ナイス', 'N人', '当たった', '取った', 'キル', '入った'.
NOTE: 'N人' / '入った' can be false positives (spotting / "entered") — the
review step trims those. Keep them: missing a kill is worse than an extra clip.
"""
import json, glob, os, re, argparse

# Precision-focused: the PLAYER's own kill reactions only.
# Deliberately EXCLUDED (caused false positives in practice):
#   - 'N人' / '入った'  -> respawn countdowns & enemy-position callouts
#   - bare 'ヒット'      -> usually the player's OWN death ("ヒット通ります")
# Death/countdown zones from detect_exclude.py are subtracted in assemble.py,
# which also removes the '取った' that is really 'HITO取ります' (=walkout).
PATTERNS = [
    r"ダウ[ーゥ〜~]*ン",     # (ワン)ダウン
    r"やった", r"ナイス",
    r"当た[っり]", r"当てた",
    r"取った", r"とった",
    r"倒した", r"キル", r"いただ(き|い)",
]
PAT = re.compile("|".join(PATTERNS))
PRE, POST, MERGE_GAP = 6.0, 2.5, 4.0

def analyze(path):
    d = json.load(open(path, encoding="utf-8"))
    dur = float(d.get("audio_duration_secs", 0) or 0)
    ws = [w for w in d.get("words", []) if w.get("type") == "word"]
    chars, tmap = [], []
    for w in ws:
        for ch in w["text"]:
            chars.append(ch)
            tmap.append((w.get("start", 0.0), w.get("speaker_id")))
    s = "".join(chars)
    return [{"t": round(tmap[m.start()][0], 2), "phrase": m.group(),
             "speaker": tmap[m.start()][1]} for m in PAT.finditer(s)], dur

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    tdir = os.path.join(a.work, "transcripts")
    out = []
    for jf in sorted(glob.glob(os.path.join(tdir, "*.json"))):
        fkey = os.path.splitext(os.path.basename(jf))[0]
        hits, dur = analyze(jf)
        wins = []
        for h in hits:
            s0, e0 = max(0.0, h["t"] - PRE), (min(dur, h["t"] + POST) if dur else h["t"] + POST)
            if wins and s0 - wins[-1]["end"] <= MERGE_GAP:
                wins[-1]["end"] = e0
                wins[-1]["phrases"].append(h["phrase"])
            else:
                wins.append({"file": fkey, "start": round(s0, 2), "end": round(e0, 2),
                             "t": h["t"], "phrases": [h["phrase"]], "speaker": h["speaker"]})
        out.extend(wins)
        print(f"{fkey}: {len(hits)} callouts -> {len(wins)} kill-clips  {[h['phrase'] for h in hits]}")
    json.dump(out, open(os.path.join(a.work, "kills.json"), "w"), ensure_ascii=False, indent=2)
    tot = sum(w["end"] - w["start"] for w in out)
    print(f"\nTOTAL kill-clips: {len(out)}, {tot:.0f}s ({tot/60:.1f} min)")

if __name__ == "__main__":
    main()
