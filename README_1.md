# Home Monitor API

A FastAPI service that receives camera images, tags them with the [Imagga](https://imagga.com) image-tagging API, stores the results in SQLite, and lets you query what was seen over a time range ("was a person detected between 9 and 10?", "what are the most common tags?").

A small client (`pi.py`) simulates a Raspberry Pi camera by uploading random images from a folder. No real camera hardware is used.

```
 pi.py (simulated camera)
        │  POST /api/image
        ▼
 FastAPI server ──► Imagga tagging API
        │
        ▼
 SQLite: images(id, timestamp, filename) ──< tags(id, imageId, tag)
        ▲
        │  GET /api/tags, /api/personDetected, /api/popularTags
     clients
```

## Run it

```bash
pip install -r requirements.txt

# Imagga API credentials
export IMAGGA_API_KEY=...
export IMAGGA_API_SECRET=...
# PowerShell: $env:IMAGGA_API_KEY="..."; $env:IMAGGA_API_SECRET="..."

uvicorn server:app --reload      # http://127.0.0.1:8000  (interactive docs at /docs)
python pi.py                     # in a second terminal: uploads simulated camera images
```

Optional environment variables: `HOME_MONITOR_DB` (default `home_monitor.db`) and `HOME_MONITOR_IMAGES` (default `images`).

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/image` | Upload an image (multipart field `file`); returns its tags |
| `GET` | `/api/tags?from=&to=` | Distinct tags seen in a time range (ISO 8601) |
| `GET` | `/api/personDetected?from=&to=` | Whether any image in the range was tagged `person` |
| `GET` | `/api/popularTags` | Top 5 tags by frequency |
| `GET` | `/api/image/{filename}` | Fetch a stored image |

```bash
curl -F "file=@photo.jpg" http://127.0.0.1:8000/api/image
# {"imageId": 1, "filename": "3f2a…c1.jpg", "tags": ["person", "room", …]}   (example shape)

curl "http://127.0.0.1:8000/api/personDetected?from=2025-01-01T00:00:00&to=2025-01-02T00:00:00"
# {"from": "2025-01-01T00:00:00", "to": "2025-01-02T00:00:00", "personDetected": true}
```

Errors: `400` for a non-image, an invalid date, or a reversed range; `413` for uploads over 5 MB; `502`/`504` when Imagga fails or times out.

## Design decisions

- **Blocking upstream call, non-blocking server.** The upload handler is a plain `def`, so FastAPI runs it in a worker thread and the slow Imagga request doesn't stall other requests. The call has a 15 s timeout.
- **One transaction per upload.** The image row and its tags are written together, so a failure can't leave an image without its tags. If tagging fails, the saved file is deleted.
- **Connection handling.** A small `db()` context manager commits on success, rolls back on error, and always closes the connection.
- **Indexes** on `images.timestamp`, `tags.imageId` and `tags.tag`, since every query filters or groups on those.
- **Input limits.** Content-type check, 5 MB size cap, and an extension allow-list; stored files get random UUID names, and the image endpoint refuses path-like names.
- **Secrets** come from environment variables, never from the repo.

## Tests

Imagga is mocked, so the tests need no credentials or network.

```bash
pip install -r requirements-dev.txt
pytest
```

They cover the upload flow, rejection of non-images and oversized files, cleanup when tagging fails, range queries, and tag ranking.

## Known limitations

- No authentication; anyone who can reach the server can upload and read images.
- Person detection is a match on Imagga's `person` tag, not a dedicated detector.
- Timestamps are the server's local time, stored without a timezone.
- SQLite and local disk storage suit a single instance, not horizontal scaling.
- Built as a school IoT project, so the camera side is simulated.
