# 🔌 API & Integration Guide

## 1. Python Library

```python
from sieve_lens import SieveLensEngine, format_report

engine = SieveLensEngine(
    zero_width_density_threshold=0.01,
    payload_min_length=16,
    oob_min_length=10,
)

obs = engine.observe("submission.docx")

print(obs.mask)                  # "1001-100"
print(obs.h_states)              # {'H1':1, 'H2':0, 'H3':0, 'H4':1, 'H5':1, 'H6':0, 'H7':0}
print(obs.evidence["H4"])        # ['paragraph 2: Ignore previous instructions...']
print(format_report(obs))        # full human-readable report


## 2. In-Memory Text
For documents already loaded as strings (no file I/O):

obs = engine.observe_text("Hello\u200b\u200bworld")
print(obs.mask)


## 3. Observation Object Reference
Field	Type	Description
source	str	File path or <text>
mask	str	7-bit mask, e.g. "1101-101"
v0_mask	str	4-bit prefix, e.g. "1101"
h_states	dict[str, int]	{"H1": 1, ..., "H7": 0}
segments	list[Segment]	Extracted text segments with metadata
evidence	dict[str, list[str]]	Per-hypothesis evidence strings
diagnostics	dict	Density values, thresholds used


## 4. FastAPI Example

from fastapi import FastAPI, UploadFile, HTTPException
from sieve_lens import SieveLensEngine
import tempfile, shutil, os

app = FastAPI(title="Sieve Lens API", version="0.0.1")
engine = SieveLensEngine()

@app.post("/api/v1/observe")
async def observe(file: UploadFile):
    suffix = os.path.splitext(file.filename)[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        obs = engine.observe(tmp_path)
    finally:
        os.unlink(tmp_path)

    if obs.h_states["H1"] == 0:
        raise HTTPException(status_code=400, detail="Unsupported or corrupt file")

    return {
        "mask": obs.mask,
        "v0_mask": obs.v0_mask,
        "h_states": obs.h_states,
        "evidence": obs.evidence,
    }

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.0.1"}

Note: FastAPI / Uvicorn are optional integration dependencies. The core
library itself has zero runtime dependencies.


## 5. Batch Processing
For a directory of documents:

from pathlib import Path
from sieve_lens import SieveLensEngine

engine = SieveLensEngine()
for path in sorted(Path("submissions").glob("*")):
    if path.suffix.lower() in {".txt", ".md", ".html", ".docx"}:
        obs = engine.observe(path)
        if obs.mask != "1000-000":
            print(f"{path.name}: {obs.mask}")