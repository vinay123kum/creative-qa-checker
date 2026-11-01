"""Frame, audio and date preparation for the QA tool."""
import datetime as dt, re, subprocess
from pathlib import Path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
FONT = (Path(__file__).parent / "fonts" / "Poppins-SemiBold.ttf").as_posix().replace(":", r"\:")
MONTHS = "January February March April May June July August September October November December".split()
DAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()


def ff(*args):
    return subprocess.run(["ffmpeg", "-hide_banner", *map(str, args)], capture_output=True, text=True, errors="replace").stderr


def check_dates(text, today=None):
    """Find 'Thursday, July 23' style dates and verify the weekday against the calendar."""
    today = today or dt.date.today()
    found = []
    pat = rf"\b({'|'.join(DAYS)})\b\W+({'|'.join(MONTHS)})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?"
    for w, m, d, y in re.findall(pat, text, re.I):
        w, m = w.title(), m.title()
        year = int(y) if y else today.year
        label = f"{w}, {m} {d}" + (f", {y}" if y else "")
        try:
            date = dt.date(year, MONTHS.index(m) + 1, int(d))
        except ValueError:
            found.append({"text": label, "weekday_ok": False, "is_past": False, "actual": "not a real date"})
            continue
        item = {"text": label, "actual": date.strftime("%A"), "weekday_ok": date.strftime("%A") == w, "is_past": date < today}
        if item not in found:
            found.append(item)
    return found


def prepare(src, out, transcribe=True):
    """Build frame sheets plus measurements. Returns a dict describing the file."""
    src, out = Path(src), Path(out); out.mkdir(parents=True, exist_ok=True)
    info = ff("-i", src)
    size = re.search(r"Video:.*?(\d{3,5}x\d{3,5})", info)
    data = {"size": size.group(1) if size else None, "images": []}
    if src.suffix.lower() in IMAGE_EXT:
        data["kind"] = "static"
        ff("-y", "-i", src, "-vf", "scale='min(1400,iw)':-2", "-q:v", 2, out / "static.jpg")
        data["images"] = ["static.jpg"]
        return data
    data["kind"] = "video"
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info).groups()
    secs = int(h) * 3600 + int(m) * 60 + float(s)
    data["seconds"] = round(secs, 2)
    label = f"drawtext=fontfile='{FONT}':text='%{{pts\\:hms}}':x=4:y=4:fontsize=16:fontcolor=yellow:box=1:boxcolor=black@0.6"
    ff("-y", "-i", src, "-vf", f"fps=2,scale=360:-1,{label},tile=6x2:padding=2", "-q:v", 3, out / "sheet_%02d.jpg")
    ff("-y", "-t", 3, "-i", src, "-vf", "fps=4,scale=270:-1,tile=6x2:padding=2", "-frames:v", 1, out / "hook.jpg")
    ff("-y", "-ss", max(0, secs - .3), "-i", src, "-frames:v", 1, "-vf", "scale=720:-1", out / "last_frame.jpg")
    data["images"] = ["hook.jpg"] + sorted(p.name for p in out.glob("sheet_*.jpg")) + ["last_frame.jpg"]
    t = sorted(float(x) for x in re.findall(r"pts_time:([\d.]+)", ff("-i", src, "-vf", "select='gt(scene,0.3)',showinfo", "-an", "-f", "null", "-")))
    cuts = [x for i, x in enumerate(t) if i == 0 or x - t[i - 1] > .25]
    data.update(cuts=len(cuts), avg_shot_seconds=round(secs / (len(cuts) + 1), 2))
    if "Audio:" in info and transcribe:
        loud = re.findall(r"I:\s+(-?[\d.]+) LUFS", ff("-i", src, "-af", "ebur128", "-f", "null", "-"))
        data["lufs"] = float(loud[-1]) if loud else None
        ff("-y", "-i", src, "-vn", "-ac", 1, "-ar", 16000, out / "audio.wav")
        import whisper
        r = whisper.load_model("small.en").transcribe(str(out / "audio.wav"), fp16=False)
        data["transcript"] = [[round(x["start"], 1), x["text"].strip()] for x in r["segments"]]
    return data


def proof_frame(src, out, seconds, name):
    ff("-y", "-ss", seconds, "-i", src, "-frames:v", 1, "-vf", "scale=300:-2", Path(out) / name)
    return name
