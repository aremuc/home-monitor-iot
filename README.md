# Home Monitor API

A FastAPI service that receives camera images, tags them using the [Imagga](https://imagga.com) image-tagging API, stores the results in SQLite, and lets you query what was seen over a time range.

For example:

- Was a person detected between 9:00 and 10:00?
- What tags were detected during a specific period?
- What are the most commonly detected tags?

A small client (`pi.py`) simulates a Raspberry Pi camera by periodically uploading random images from a local folder. No physical camera hardware is required.

## Architecture

```text
pi.py (simulated camera)
       │
       │ POST /api/image
       ▼
FastAPI server ─────► Imagga tagging API
       │
       ▼
SQLite database
       │
       ├── images(id, timestamp, filename)
       └── tags(id, imageId, tag)
       ▲
       │
       │ GET /api/tags
       │ GET /api/personDetected
       │ GET /api/popularTags
       │
    clients
```

## Run it

Install the runtime dependencies:

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your Imagga credentials:

```text
IMAGGA_API_KEY=your_api_key_here
IMAGGA_API_SECRET=your_api_secret_here
```

Then start the API:

```bash
uvicorn server:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

FastAPI's interactive documentation is available at:

```text
http://127.0.0.1:8000/docs
```

In a second terminal, start the simulated camera client:

```bash
python pi.py
```

### Optional configuration

The following environment variables can also be configured:

- `HOME_MONITOR_DB` — SQLite database path. Defaults to `home_monitor.db`.
- `HOME_MONITOR_IMAGES` — directory used to store uploaded images. Defaults to `images`.
- `HOME_MONITOR_SERVER_URL` — API endpoint used by `pi.py`. Defaults to `http://127.0.0.1:8000/api/image`.

See `.env.example` for the available configuration values.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/image` | Upload an image and return its detected tags |
| `GET` | `/api/tags?from=&to=` | Return distinct tags detected within a time range |
| `GET` | `/api/personDetected?from=&to=` | Check whether a person was detected within a time range |
| `GET` | `/api/popularTags` | Return the five most frequently detected tags |
| `GET` | `/api/image/{filename}` | Retrieve a stored image |

### Example

Upload an image:

```bash
curl -F "file=@photo.jpg" http://127.0.0.1:8000/api/image
```

Example response:

```json
{
  "imageId": 1,
  "filename": "3f2ac1.jpg",
  "tags": ["person", "room"]
}
```

Check whether a person was detected during a time range:

```bash
curl "http://127.0.0.1:8000/api/personDetected?from=2025-01-01T00:00:00&to=2025-01-02T00:00:00"
```

Example response:

```json
{
  "from": "2025-01-01T00:00:00",
  "to": "2025-01-02T00:00:00",
  "personDetected": true
}
```

The API returns:

- `400` for invalid image uploads, invalid dates, or reversed time ranges
- `413` for image uploads larger than 5 MB
- `502` when the external tagging service fails
- `504` when the external tagging service times out

## Design decisions

- **Blocking upstream call, non-blocking server.** The upload handler is defined using a standard `def`, allowing FastAPI to run the blocking Imagga request in a worker thread rather than blocking the event loop.
- **Transactional uploads.** The image record and its tags are stored in one database transaction so a partial database write cannot leave inconsistent records.
- **Failure cleanup.** If image tagging fails, the uploaded file is removed rather than leaving an orphaned image on disk.
- **Database connection handling.** A context manager commits successful operations, rolls back failures, and always closes the SQLite connection.
- **Database indexes.** Indexes are created for timestamps, image/tag relationships, and tag values used by the application's queries.
- **Input limits.** Uploads are restricted by content type, file size, and allowed extensions. Stored images receive randomized UUID filenames.
- **Secret management.** API credentials are loaded from environment variables rather than stored in the repository.
- **External service timeout.** Requests to Imagga use a 15-second timeout and return appropriate upstream error responses.

## Tests

Install the development dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the test suite:

```bash
pytest
```

Imagga is mocked during testing, so the tests do not require API credentials or network access.

The test suite covers:

- successful image uploads and tag storage
- rejection of non-image uploads
- upload size limits
- cleanup when the tagging service fails
- tag queries by time range
- person detection queries
- invalid and reversed time ranges
- popular-tag ranking

## Known limitations

- The API does not currently implement authentication.
- Person detection relies on Imagga returning a `person` tag rather than using a dedicated object-detection model.
- Timestamps use the server's local time and are stored without timezone information.
- SQLite and local disk storage are intended for a single-instance deployment rather than horizontal scaling.
- The camera client is simulated because the project was originally developed as an IoT coursework project.