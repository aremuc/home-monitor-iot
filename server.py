"""Home monitor API.

Receives images from a (simulated) camera client, tags them with the Imagga
image-tagging API, and stores the results in SQLite so they can be queried
by time range.
"""

import os
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime

import requests
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

DB_PATH = os.getenv("HOME_MONITOR_DB", "home_monitor.db")
IMAGES_DIR = os.getenv("HOME_MONITOR_IMAGES", "images")
TAGS_URL = "https://api.imagga.com/v2/tags"

IMAGGA_TIMEOUT_SECONDS = 15
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

@contextmanager
def db():
    """Open a connection, commit on success, roll back on error, always close."""
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                filename TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                imageId INTEGER NOT NULL,
                tag TEXT NOT NULL,
                FOREIGN KEY (imageId) REFERENCES images(id)
            );
            CREATE INDEX IF NOT EXISTS idx_images_timestamp ON images(timestamp);
            CREATE INDEX IF NOT EXISTS idx_tags_image ON tags(imageId);
            CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
            """
        )


def save_image_with_tags(filename: str, tags: list[str]) -> int:
    """Insert the image row and its tags in a single transaction."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO images (timestamp, filename) VALUES (?, ?)",
            (timestamp, filename),
        )
        image_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO tags (imageId, tag) VALUES (?, ?)",
            [(image_id, tag) for tag in tags],
        )
    return image_id


# --------------------------------------------------------------------------
# Imagga integration
# --------------------------------------------------------------------------

class TaggingError(Exception):
    """Raised when the tagging service fails; carries the HTTP status to return."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def call_imagga_tags(image_path: str) -> list[str]:
    # Credentials are read per call so the server can start (and be tested)
    # without them.
    api_key = os.getenv("IMAGGA_API_KEY")
    api_secret = os.getenv("IMAGGA_API_SECRET")
    if not api_key or not api_secret:
        raise TaggingError(
            "IMAGGA_API_KEY and IMAGGA_API_SECRET must be set", status_code=500
        )

    try:
        with open(image_path, "rb") as img:
            response = requests.post(
                TAGS_URL,
                auth=(api_key, api_secret),
                files={"image": img},
                timeout=IMAGGA_TIMEOUT_SECONDS,
            )
    except requests.Timeout:
        raise TaggingError("Imagga request timed out", status_code=504)
    except requests.RequestException as exc:
        raise TaggingError(f"Could not reach Imagga: {exc}")

    if response.status_code != 200:
        raise TaggingError(f"Imagga error {response.status_code}: {response.text}")

    tags_data = response.json().get("result", {}).get("tags", [])
    return [t["tag"]["en"] for t in tags_data if "tag" in t and "en" in t["tag"]]


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(IMAGES_DIR, exist_ok=True)
    init_db()
    yield


app = FastAPI(title="Home Monitor API", lifespan=lifespan)


def parse_range(from_: str, to: str) -> tuple[str, str]:
    try:
        start = datetime.fromisoformat(from_)
        end = datetime.fromisoformat(to)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid datetime format, use ISO (e.g. 2025-01-01T10:00:00)",
        )
    if start > end:
        raise HTTPException(status_code=400, detail="'from' must not be after 'to'")
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


@app.get("/")
def root():
    return {"status": "ok", "message": "Home monitoring API running"}


# Declared as a plain `def` on purpose: FastAPI runs it in a worker thread, so
# the blocking Imagga call does not stall the event loop.
@app.post("/api/image")
def upload_image(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    contents = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".jpg"

    unique_name = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(IMAGES_DIR, unique_name)
    with open(save_path, "wb") as out:
        out.write(contents)

    try:
        tags = call_imagga_tags(save_path)
        image_id = save_image_with_tags(unique_name, tags)
    except TaggingError as exc:
        os.remove(save_path)
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception:
        os.remove(save_path)
        raise

    return {"imageId": image_id, "filename": unique_name, "tags": tags}


@app.get("/api/tags")
def get_tags(from_: str = Query(..., alias="from"), to: str = Query(...)):
    start_iso, end_iso = parse_range(from_, to)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT t.tag
            FROM tags t
            JOIN images i ON t.imageId = i.id
            WHERE i.timestamp BETWEEN ? AND ?
            """,
            (start_iso, end_iso),
        ).fetchall()
    return {"from": start_iso, "to": end_iso, "tags": [r[0] for r in rows]}


@app.get("/api/personDetected")
def person_detected(from_: str = Query(..., alias="from"), to: str = Query(...)):
    start_iso, end_iso = parse_range(from_, to)
    with db() as conn:
        (count,) = conn.execute(
            """
            SELECT COUNT(*)
            FROM tags t
            JOIN images i ON t.imageId = i.id
            WHERE i.timestamp BETWEEN ? AND ?
              AND LOWER(t.tag) = 'person'
            """,
            (start_iso, end_iso),
        ).fetchone()
    return {"from": start_iso, "to": end_iso, "personDetected": count > 0}


@app.get("/api/popularTags")
def popular_tags():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT tag, COUNT(*) AS cnt
            FROM tags
            GROUP BY tag
            ORDER BY cnt DESC
            LIMIT 5
            """
        ).fetchall()
    return [{"tag": tag, "count": cnt} for tag, cnt in rows]


@app.get("/api/image/{filename}")
def get_image(filename: str):
    # basename() guards against path traversal even though FastAPI's path
    # parameter already excludes slashes.
    safe_name = os.path.basename(filename)
    path = os.path.join(IMAGES_DIR, safe_name)
    if safe_name != filename or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path)
