from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
import sqlite3
from pathlib import Path
from datetime import datetime
import uuid
import os
import requests

DB_PATH = "home_monitor.db"

API_KEY = os.getenv("IMAGGA_API_KEY")
API_SECRET = os.getenv("IMAGGA_API_SECRET")

TAGS_URL = "https://api.imagga.com/v2/tags"

IMAGES_DIR = "images"
os.makedirs(IMAGES_DIR, exist_ok=True)

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            filename TEXT NOT NULL
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imageId INTEGER NOT NULL,
            tag TEXT NOT NULL,
            FOREIGN KEY (imageId) REFERENCES images(id)
        );
    """)

    conn.commit()
    conn.close()

def insert_img(filename: str) -> int:
    conn = get_connection()
    cur = conn.cursor()
    timestamp = datetime.now().isoformat(timespec="seconds")
    cur.execute(
        "INSERT INTO images (timestamp, filename) VALUES (?, ?)",
        (timestamp, filename)
    )
    image_id = cur.lastrowid
    conn.commit()
    conn.close()
    return image_id

def insert_tags(image_id: int, tags: list[str]) -> None:
    if not tags:
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.executemany(
        "INSERT INTO tags (imageId, tag) VALUES (?, ?)",
        [(image_id, tag) for tag in tags]
    )
    conn.commit()
    conn.close()

def call_imagga_tags(image_path: str) -> list[str]:
    with open(image_path, "rb") as img:
        response = requests.post(
            TAGS_URL,
            auth=(API_KEY, API_SECRET),
            files={"image": img}
        )

    if response.status_code != 200:
        raise RuntimeError(f"Imagga error {response.status_code}: {response.text}")

    data = response.json()
    tags_data = data.get("result", {}).get("tags", [])
    tags = [t["tag"]["en"] for t in tags_data if "tag" in t and "en" in t["tag"]]
    return tags


app = FastAPI()

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/")
def root():
    return {"status": "ok", "message": "Home monitoring API running"}

@app.post("/api/image")
async def upload_image(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    _, ext = os.path.splitext(file.filename)
    if not ext:
        ext = ".jpg"  
    unique_name = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(IMAGES_DIR, unique_name)

    contents = await file.read()
    with open(save_path, "wb") as out:
        out.write(contents)

    try:
        tags = call_imagga_tags(save_path)
    except Exception as e:
        if os.path.exists(save_path):
            os.remove(save_path)
        raise HTTPException(status_code=500, detail=str(e))

    image_id = insert_img(unique_name)
    insert_tags(image_id, tags)

    return {
        "imageId": image_id,
        "filename": unique_name,
        "tags": tags
    }

@app.get("/api/tags")
def get_tags(
    from_: str = Query(..., alias="from"),
    to: str = Query(..., alias="to")
):
    try:
        start = datetime.fromisoformat(from_)
        end = datetime.fromisoformat(to)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format, use ISO (e.g. 2025-01-01T10:00:00)")

    start_iso = start.isoformat(timespec="seconds")
    end_iso = end.isoformat(timespec="seconds")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT t.tag
        FROM tags t
        JOIN images i ON t.imageId = i.id
        WHERE i.timestamp BETWEEN ? AND ?
        """,
        (start_iso, end_iso)
    )
    rows = cur.fetchall()
    conn.close()

    tags = [r[0] for r in rows]

    return {
        "from": start_iso,
        "to": end_iso,
        "tags": tags
    }

@app.get("/api/personDetected")
def person_detected(
    from_: str = Query(..., alias="from"),
    to: str = Query(..., alias="to")
):
    try:
        start = datetime.fromisoformat(from_)
        end = datetime.fromisoformat(to)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format, use ISO (e.g. 2025-01-01T10:00:00)")

    start_iso = start.isoformat(timespec="seconds")
    end_iso = end.isoformat(timespec="seconds")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*)
        FROM tags t
        JOIN images i ON t.imageId = i.id
        WHERE i.timestamp BETWEEN ? AND ?
          AND LOWER(t.tag) = 'person'
        """,
        (start_iso, end_iso)
    )
    count = cur.fetchone()[0]
    conn.close()

    return {
        "from": start_iso,
        "to": end_iso,
        "personDetected": bool(count > 0)
    }

@app.get("/api/popularTags")
def popular_tags():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT tag, COUNT(*) as cnt
        FROM tags
        GROUP BY tag
        ORDER BY cnt DESC
        LIMIT 5
        """
    )
    rows = cur.fetchall()
    conn.close()

    return [
        {"tag": tag, "count": cnt}
        for (tag, cnt) in rows
    ]

@app.get("/api/image/{filename}")
def get_image(filename: str):
    path = os.path.join(IMAGES_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path)