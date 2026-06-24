"""Detect EXCLUSION zones from Scribe transcripts: moments that must never
appear in the highlight.

1) Respawn countdowns  — the player/announcer counts "1,2,3...10" (or
   いち,に,さん... / "5678910") while waiting to respawn. Detected as >=4
   number-like tokens within a short window.
   NOTE: '*'ナイス'*' is said on BOTH kills AND deaths (the player compliments
   the opponent who tagged them). So the death pre-roll is 10s — wide enough to
   swallow a 'ナイス' said just before the player announces their own hit.
2) Own-death / walkout  — "ヒット通ります / ヒットです / フィールドアウト",
   often mis-transcribed by Scribe as "HITO取ります / ひっておりまーす /
   いております / おりまーす". These mark the player getting tagged and
   leaving, plus the dull walk back.

Output <work>/exclude.json -> [{file,start,end,kind}, ...]
Usage: python detect_exclude.py --work <edit_dir>
"""
import json, glob, os, re, argparse

# death / walkout markers (incl. common Scribe mis-hearings of ヒット通ります)
DEATH = re.compile(
    r"ヒットです|ヒット通|ヒットしま|フィールドアウト|HITO取|ひっており|"
    r"ひとりまー|ひとります|おりまーす|いております|いておりま|通りまーす|通ります")

# number tokens (digits, fullwidth, kanji, kana readings) for countdown runs
NUM = re.compile(r"^(?:[0-9０-９]+|[一二三四五六七八九十]|"
                 r"いち|に|さん|し|ご|ろく|なな|しち|はち|きゅう|く|じゅう|"
                 r"ゼロ|ワン|ツー|スリー)$")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    out = []
    for jf in sorted(glob.glob(os.path.join(a.work, "transcripts", "*.json"))):
        fk = os.path.splitext(os.path.basename(jf))[0]
        d = json.load(open(jf, encoding="utf-8"))
        ws = [w for w in d.get("words", []) if w.get("type") == "word"]
        dur = float(d.get("audio_duration_secs", 0) or 0)

        # 1) death/walkout via concatenated-char search
        chars, tmap = [], []
        for w in ws:
            for ch in w["text"]:
                chars.append(ch); tmap.append(w.get("start", 0.0))
        s = "".join(chars)
        for m in DEATH.finditer(s):
            t = tmap[m.start()]
            # pre-roll 10s: catch the "ナイス" the player says complimenting the
            # opponent right BEFORE announcing their own hit (ナイス is said on
            # both kills AND deaths, so it can't be trusted near a death marker).
            out.append({"file": fk, "start": round(max(0, t - 10), 2),
                        "end": round((min(dur, t + 10) if dur else t + 10), 2),
                        "kind": "death"})

        # 2) countdown: >=4 number-like tokens within 5s
        nums = [(w.get("start", 0.0)) for w in ws
                if NUM.match(w["text"]) or re.search(r"[0-9０-９]{3,}", w["text"])]
        i = 0
        while i < len(nums):
            j = i
            while j + 1 < len(nums) and nums[j + 1] - nums[j] <= 2.0:
                j += 1
            if j - i + 1 >= 4:
                out.append({"file": fk, "start": round(max(0, nums[i] - 2), 2),
                            "end": round((min(dur, nums[j] + 5) if dur else nums[j] + 5), 2),
                            "kind": "countdown"})
            i = j + 1

    # merge overlapping zones per file
    byf = {}
    for z in out:
        byf.setdefault(z["file"], []).append(z)
    merged = []
    for f, zs in byf.items():
        zs.sort(key=lambda x: x["start"])
        cur = None
        for z in zs:
            if cur and z["start"] <= cur["end"]:
                cur["end"] = max(cur["end"], z["end"])
                cur["kind"] = cur["kind"] if cur["kind"] == z["kind"] else "mix"
            else:
                if cur: merged.append(cur)
                cur = dict(z)
        if cur: merged.append(cur)

    json.dump(merged, open(os.path.join(a.work, "exclude.json"), "w"),
              ensure_ascii=False, indent=2)
    tot = sum(z["end"] - z["start"] for z in merged)
    print(f"exclude zones: {len(merged)}, {tot:.0f}s ({tot/60:.1f} min)")
    for f in sorted(byf):
        zs = [z for z in merged if z["file"] == f]
        if zs:
            print(f"  {f}: {len(zs)} zones "
                  f"({sum(1 for z in zs if z['kind']!='death')} count, "
                  f"{sum(1 for z in zs if z['kind']=='death')} death)")

if __name__ == "__main__":
    main()
