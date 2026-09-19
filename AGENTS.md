# Project guidance

- Face enrollment and naming are automatic. Do not restore manual `e` or `n`
  controls. An unnamed, enrolled person should move from a stable temporary ID
  to their learned name; do not create a second record when the face already
  matches an enrolled one.
- Support up to two independently tracked faces. Split diarized clips into
  turns and attribute a turn only when one stable face clearly shows matching
  mouth activity and the other visible face has reliable, inactive evidence.
  Keep overlap, offscreen speech, uncertain tracking, and more than two visible
  faces unassigned. Clip-local voice labels are never persistent face identities.
- Require corroborated name evidence from two distinct audio clips, not merely
  two turns or retries. Corrections also need explicit spoken correction evidence.
  Validate every citation against the same stable person ID before saving facts
  or names. Preserve candidate evidence across sessions.
- Route automatic naming and manual corrections through the same name assignment
  operation. Keep the stable person ID, update the record, rename every saved
  face file for that person, and update every image path. For the current single
  image design, the canonical filename is exactly `<name>.png`.
- The local JSON manifest is temporary storage. When a database is introduced,
  keep each person linked to an existing image and preserve the name-to-image
  filename convention. Do not delete or orphan saved faces during migration.
- New transcripts go directly to the background Gemini coordinator. Do not
  restore ongoing transcript logging. Pending speech and recent conversation
  stay in bounded memory; only names, facts, candidates, and their supporting
  attributed text are durable. Report discarded pending speech on exit.
- The legacy `data/voice_events.jsonl` is read only for migration. Preserve fact
  evidence, replay eligible attributed events, and delete the old log only after
  successful migration. Retain it on failure or concurrent modification. Never
  retrospectively assign legacy unassigned speech without visual evidence.
- Derive model, data, and camera bridge paths from the cloned project or explicit
  CLI options. Do not hardcode a developer's home directory or WSL distribution.
  Never commit API keys or raw microphone audio.
