# Project guidance

- Manual face enrollment (`e`) and name entry (`n`) are temporary user controls.
  Keep both available as overrides when automatic identity naming is added.
- Future voice transcription and context processing should assign a name only
  after enough supporting information has been gathered. An unnamed, enrolled
  person should move from a stable temporary ID to their learned name; do not
  create a second person record when the face already matches an enrolled one.
- Route automatic naming and manual corrections through the same name assignment
  operation. Keep the stable person ID, update the record, rename every saved
  face file for that person, and update every image path. For the current single
  image design, the canonical filename is exactly `<name>.png`.
- The local JSON manifest is temporary storage. When a database is introduced,
  keep each person linked to an existing image and preserve the name-to-image
  filename convention. Do not delete or orphan saved faces during migration.
- Derive model, data, and camera bridge paths from the cloned project or explicit
  CLI options. Do not hardcode a developer's home directory or WSL distribution.
