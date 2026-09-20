# Frontend

The Next.js application runs separately from the Python backend. Start the
backend from `backend/` with:

```text
uvicorn tracker_engine.api:create_app --factory
```

Start the frontend from `frontend/` with:

```text
npm install
npm run dev
```

Open `http://localhost:3000`. The frontend API client uses
`http://localhost:8000` by default; set `NEXT_PUBLIC_SERVER_URL` if the backend
runs elsewhere.

`/` is the live camera view. Start `python -m tracker_engine --camera 0` from
`backend/` to publish frames to the API. The browser reconnects automatically
and reports unavailable or stale feeds. The focused person's saved details
appear below the image, and bounding boxes follow the same displayed frame.

`/memories` lists actual saved text notes by file modification date; note edits
retain their IDs and paths. Text notes belong to one enrolled person at a time.
`/person/[id]` shows saved facts, notes, name correction, and evidence-backed
shared events. Person names may be null while automatic naming gathers evidence.
See [Stages 7–12 checks](../backend/STAGE_7_TO_12_CHECKS.md) for the browser
and graph review procedure.
