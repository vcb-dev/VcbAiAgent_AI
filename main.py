"""VCB_AI entry point: planner, footage matching, timeline build and FFmpeg render.

Run:  python main.py          (or: uvicorn main:app --port 8787 --reload)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")

from app import app  # noqa: E402,F401

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8787")), reload=os.environ.get("RELOAD") == "1")
