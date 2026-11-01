"""Creative QA checker: upload a video or static, get a QA report. Run: python app.py, then open :8040."""
import json, threading, uuid
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import core, engine

ROOT = Path(__file__).parent
JOBS = ROOT / "jobs"; JOBS.mkdir(exist_ok=True)
FACTS = json.loads((ROOT / "facts.json").read_text(encoding="utf-8"))
MAX_BYTES = 800 * 1024 * 1024
app = FastAPI(title="Creative QA Checker")
app.mount("/files", StaticFiles(directory=JOBS), name="files")
pages = Jinja2Templates(directory=ROOT / "templates")


def save(job, **fields):
    p = JOBS / job / "job.json"
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    d.update(fields); p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def work(job, src, brief, location):
    out = JOBS / job
    try:
        save(job, status="Reading frames and audio")
        data = core.prepare(src, out)
        dates = core.check_dates(brief)
        save(job, status="Claude is reviewing it")
        facts = {"brand": FACTS["brand_spelling"], "description": FACTS.get("brand_description", ""), "banned_phrases": FACTS.get("banned_phrases", []), "location": FACTS["locations"].get(location)}
        rep = engine.review(data, brief, location, facts, dates, out)
        dates += [d for line in rep["on_screen_text"] for d in core.check_dates(line) if d not in dates]
        for i, c in enumerate(rep["checks"]):
            if data["kind"] == "video" and c.get("proof_seconds") is not None and c["result"] != "Pass":
                c["proof"] = core.proof_frame(src, out, c["proof_seconds"], f"proof_{i}.jpg")
        total = sum(s["score"] for s in rep["scores"])
        band = "Strong" if total >= 85 else "Good" if total >= 70 else "Average" if total >= 50 else "Low"
        save(job, status="done", report=rep, data={k: v for k, v in data.items() if k != "images"},
             dates=dates, total=total, band=band, areas=engine.AREAS)
    except Exception as e:
        save(job, status="failed", error=str(e))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return pages.TemplateResponse(request, "home.html", {"locations": list(FACTS["locations"]), "brand": FACTS["brand_spelling"]})


@app.post("/check")
def check(file: UploadFile = File(...), brief: str = Form(""), location: str = Form("")):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in core.IMAGE_EXT | core.VIDEO_EXT:
        raise HTTPException(400, "Upload an MP4, MOV, WEBM, PNG, JPG or WEBP file.")
    job = uuid.uuid4().hex[:12]; (JOBS / job).mkdir()
    src = JOBS / job / f"upload{ext}"; size = 0
    with src.open("wb") as f:
        while chunk := file.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(400, "File is over 800 MB.")
            f.write(chunk)
    save(job, status="Queued", name=Path(file.filename).name, location=location)
    threading.Thread(target=work, args=(job, src, brief, location), daemon=True).start()
    return RedirectResponse(f"/job/{job}", 303)


@app.get("/job/{job}", response_class=HTMLResponse)
def show(request: Request, job: str):
    p = JOBS / job / "job.json"
    if not job.isalnum() or not p.exists():
        raise HTTPException(404)
    return pages.TemplateResponse(request, "job.html", {"job": job, "j": json.loads(p.read_text(encoding="utf-8"))})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8040)
