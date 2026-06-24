"""Build the final edit list from detected segments + kill clips, honoring a
per-round recall FLOOR from hand-sign labels.

Priority order when selecting clips:
  1. Kill-callout clips     -> always kept (minus exclusion zones).
  2. Per-round floor        -> each round labeled N hits (file stem '_N') gets
                               at least N distinct scenes (top score, spaced).
                               Hand signs UNDER-report, so the label is a floor;
                               extra clips are fine (recall > precision here).
  3. Global fill            -> best remaining combat up to --target seconds.
Then exclusion zones are subtracted, 0-hit rounds optionally dropped, and the
result ordered chronologically by capture order.

Usage:
    python assemble.py --work <edit_dir> [--target 700] [--cap 120]
                       [--min 3.5] [--drop-zero]

Reads <work>/seg_*.json, optional <work>/kills.json, <work>/exclude.json.
Round labels come from the file stem suffix (GH015233_2 -> 2, _missing -> none).
Writes <work>/editlist.json.
"""
import json, glob, os, re, argparse

def gopro_key(fkey):
    m = re.match(r"G[HX](\d{2})(\d{4})(?:_.+)?$", fkey)
    return (int(m.group(2)), int(m.group(1))) if m else (10**9, fkey)

def label_of(fkey):
    m = re.search(r"_(\d+)$", fkey)   # numeric hit label, else None
    return int(m.group(1)) if m else None

def overlaps(s, e, zones, thresh=1.5):
    return sum(max(0, min(e, ze) - max(s, zs)) for zs, ze in zones) > thresh

def spaced(s, e, chosen, gap=0.5):
    return all(s - c[1] > gap or c[0] - e > gap for c in chosen)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--target", type=float, default=700.0)
    ap.add_argument("--cap", type=float, default=120.0)
    ap.add_argument("--min", type=float, default=3.5)
    ap.add_argument("--drop-zero", action="store_true")
    a = ap.parse_args()

    ex = {}
    expath = os.path.join(a.work, "exclude.json")
    if os.path.exists(expath):
        for z in json.load(open(expath, encoding="utf-8")):
            ex.setdefault(z["file"], []).append((z["start"], z["end"]))

    # combat candidates per file (drop those overlapping exclusion zones)
    pool = {}
    for jf in glob.glob(os.path.join(a.work, "seg_*.json")):
        d = json.load(open(jf))
        f = os.path.splitext(os.path.basename(d["video"]))[0]
        for s in d["segments"]:
            if s["end"] - s["start"] < a.min:
                continue
            if overlaps(s["start"], s["end"], ex.get(f, [])):
                continue
            pool.setdefault(f, []).append({"file": f, "start": s["start"],
                "end": s["end"], "score": s["score"], "kill": False, "phrases": ""})
    for f in pool:
        pool[f].sort(key=lambda x: x["score"], reverse=True)

    chosen = {f: [] for f in pool}

    # 1. kill clips (always; minus exclusion)
    kills = {}
    kpath = os.path.join(a.work, "kills.json")
    if os.path.exists(kpath):
        for k in json.load(open(kpath, encoding="utf-8")):
            f = k["file"]
            if overlaps(k["start"], k["end"], ex.get(f, [])):
                continue
            ph = "/".join(dict.fromkeys(k.get("phrases", [])))
            kills.setdefault(f, []).append({"file": f, "start": k["start"],
                "end": k["end"], "score": 1.0, "kill": True, "phrases": ph})
    for f, ks in kills.items():
        chosen.setdefault(f, []).extend(ks)

    def n_scenes(f):  # distinct scenes already chosen for file f
        iv = sorted([(c["start"], c["end"]) for c in chosen[f]])
        cnt, last = 0, -1e9
        for s, e in iv:
            if s - last > 0.5:
                cnt += 1
            last = max(last, e)
        return cnt

    # 2. per-round floor: ensure >= label distinct scenes
    for f in pool:
        N = label_of(f)
        if not N:
            continue
        for c in pool[f]:
            if n_scenes(f) >= N:
                break
            if spaced(c["start"], c["end"], [(x["start"], x["end"]) for x in chosen[f]]):
                chosen[f].append(c)

    # 3. global fill to target with remaining combat (score order, capped/file)
    chosen_keys = {f: {(c["start"], c["end"]) for c in chosen[f]} for f in chosen}
    used = {f: sum(c["end"] - c["start"] for c in chosen[f]) for f in chosen}
    total = sum(used.values())
    allc = sorted([c for f in pool for c in pool[f]],
                  key=lambda x: x["score"], reverse=True)
    for c in allc:
        if total >= a.target:
            break
        f = c["file"]
        if (c["start"], c["end"]) in chosen_keys[f] or used.get(f, 0) >= a.cap:
            continue
        chosen[f].append(c)
        chosen_keys[f].add((c["start"], c["end"]))
        used[f] += c["end"] - c["start"]
        total += c["end"] - c["start"]

    # merge overlapping per file
    merged = []
    for f, cs in chosen.items():
        cs.sort(key=lambda x: x["start"])
        cur = None
        for c in cs:
            if cur and c["start"] - cur["end"] <= 0.5:
                cur["end"] = max(cur["end"], c["end"])
                if c["kill"]:
                    cur["kill"] = True
                    cur["phrases"] = (cur.get("phrases", "") + " " + c["phrases"]).strip()
            else:
                if cur:
                    merged.append(cur)
                cur = dict(c)
        if cur:
            merged.append(cur)

    if a.drop_zero:
        before = len(merged)
        merged = [m for m in merged if not m["file"].endswith("_0")]
        print(f"  dropped {before - len(merged)} clips from 0-hit games")

    for m in merged:
        m["start"], m["end"] = round(m["start"], 2), round(m["end"], 2)
        m["dur"] = round(m["end"] - m["start"], 2)
        m.pop("score", None)
    merged.sort(key=lambda x: (gopro_key(x["file"]), x["start"]))
    json.dump(merged, open(os.path.join(a.work, "editlist.json"), "w"),
              ensure_ascii=False, indent=2)

    tot = sum(m["dur"] for m in merged)
    nk = sum(1 for m in merged if m["kill"])
    print(f"editlist: {len(merged)} clips, {tot/60:.1f} min ({tot:.0f}s); {nk} kill")
    # report per-round scenes vs label floor
    from collections import defaultdict
    cnt = defaultdict(int)
    for m in merged:
        cnt[m["file"]] += 1
    for f in sorted(cnt, key=gopro_key):
        N = label_of(f)
        flag = "" if (N is None or cnt[f] >= N) else "  <FLOOR MISS>"
        print(f"  {f}: {cnt[f]} scenes (label={N}){flag}")

if __name__ == "__main__":
    main()
