# Project guidance

- Face enrollment and naming are automatic. Do not restore manual `e` or `n`
  controls. An unnamed, enrolled person should move from a stable temporary ID
  to their learned name; do not create a second record when the face already
  matches an enrolled one.
- Attribute speech to a face only when one stable face is visible, its mouth
  motion aligns with speech, and the clip has one identifiable audio speaker.
  Keep overlapping or offscreen speech unassigned. Require corroborated name
  evidence from separate attributed clips before naming; corrections also need
  an explicit spoken correction.
- Route automatic naming and manual corrections through the same name assignment
  operation. Keep the stable person ID, update the record, rename every saved
  face file for that person, and update every image path. For the current single
  image design, the canonical filename is exactly `<name>.png`.
- The local JSON manifest is temporary storage. When a database is introduced,
  keep each person linked to an existing image and preserve the name-to-image
  filename convention. Do not delete or orphan saved faces during migration.
- `data/voice_events.jsonl` is a temporary local transcript spool while Gemini
  handoff is incomplete. Once new transcripts can be handed directly to Gemini
  with reliable retry, migrate any pending events and remove this local transcript
  saving. Preserve the per-person facts and their evidence during that change.
- Derive model, data, and camera bridge paths from the cloned project or explicit
  CLI options. Do not hardcode a developer's home directory or WSL distribution.
  Never commit API keys or raw microphone audio.
