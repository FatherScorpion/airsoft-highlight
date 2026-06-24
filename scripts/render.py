"""Render the highlight from an edit list.

Per clip: accurate seek + re-encode to uniform params (1080p / 59.94fps /
yuv420p / AAC) with short audio fades to kill cut clicks. Then concat
(stream copy) into the output. Original audio preserved.

Optional top-left caption per round: "N試合目：MHit" where N is the game's
position in the day's capture order and M is the hit count from --labels.

Concat uses RELATIVE ascii filenames and cwd=<clips dir> so non-ASCII (e.g.
Japanese) directory paths don't get mangled by ffmpeg's concat demuxer.

Usage:
    python render.py --videos <dir> --work <edit_dir> --out highlight.mp4
                     [--list editlist.json] [--labels hit_labels.json]
                     [--crf 20] [--preset veryfast]

--labels: JSON mapping fileid (4-digit GoPro id, e.g. "5233") OR full stem to
          hit count, e.g. {"5233": 2, "5234": 0}. Rounds missing a label get
          no caption.
"""
import json, os, re, glob, subprocess, sys, argparse

FONT = "C\\:/Windows/Fonts/meiryob.ttc"  # bold Japanese gothic; ':' escaped for ffmpeg

def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        sys.stdout.write(r.stdout.decode("utf-8", "ignore")[-1500:])
        raise SystemExit("ffmpeg failed")

def fileid(stem):
    m = re.match(r"G[HX]\d{2}(\d{4})", stem)
    return m.group(1) if m else stem

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--list", default="editlist.json")
    ap.add_argument("--labels", default=None)
    ap.add_argument("--crf", default="20")
    ap.add_argument("--preset", default="veryfast")
    a = ap.parse_args()

    clips = json.load(open(os.path.join(a.work, a.list), encoding="utf-8"))

    # game numbers from the day's capture order (all source MP4s, unique fileid)
    ids = sorted({fileid(os.path.splitext(os.path.basename(p))[0])
                  for p in glob.glob(os.path.join(a.videos, "*.MP4"))})
    game_no = {fid: i + 1 for i, fid in enumerate(ids)}

    labels = {}
    if a.labels:
        raw = json.load(open(a.labels, encoding="utf-8"))
        for k, v in raw.items():
            labels[fileid(k)] = v   # normalize keys to fileid

    tmp = os.path.join(a.work, "clips")
    os.makedirs(tmp, exist_ok=True)
    names = []
    for i, c in enumerate(clips):
        src = os.path.join(a.videos, c["file"] + ".MP4")
        dur = c["dur"]
        out = os.path.join(tmp, f"c{i:03d}.mp4")
        fo = max(0.0, dur - 0.05)
        af = f"afade=t=in:st=0:d=0.02,afade=t=out:st={fo:.3f}:d=0.05"
        vf = ("scale=1920:1080:force_original_aspect_ratio=decrease,"
              "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=60000/1001,format=yuv420p")
        fid = fileid(c["file"])
        if fid in labels and fid in game_no:
            # fullwidth colon '：' avoids ffmpeg ':' escaping inside text
            txt = f"{game_no[fid]}試合目：{labels[fid]}Hit"
            vf += (f",drawtext=fontfile='{FONT}':text='{txt}':"
                   "x=36:y=30:fontsize=46:fontcolor=white:"
                   "box=1:boxcolor=black@0.55:boxborderw=14")
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(c["start"]), "-i", src, "-t", str(dur),
             "-vf", vf, "-af", af,
             "-c:v", "libx264", "-crf", a.crf, "-preset", a.preset,
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out])
        names.append(f"c{i:03d}.mp4")
        tag = "KILL" if c.get("kill") else "    "
        print(f"[{i+1}/{len(clips)}] {tag} {c['file']} {c['start']:.1f}s +{dur:.1f}s", flush=True)

    open(os.path.join(tmp, "concat.txt"), "w").write(
        "\n".join(f"file '{n}'" for n in names) + "\n")
    out_abs = os.path.abspath(a.out)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", out_abs],
        cwd=tmp)
    print("DONE ->", out_abs)

if __name__ == "__main__":
    main()
