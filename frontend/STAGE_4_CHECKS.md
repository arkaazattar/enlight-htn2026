# Stage 4 people display checks

The people sidebar reads `GET /people` and links each tile by the saved stable
person ID. The person page reads `GET /people/{person_id}` and shows its label,
ID, face image, saved facts, and any fact evidence attributed to that same ID.
Missing images fall back to an icon. Neither view derives identity from a
graph name, filename, list position, or mock record. The dashboard timeline
still has sample memories; stored note presentation belongs to Stage 8.

## Automated checks

From `frontend/`:

```text
npm exec tsc -- --noEmit
npm exec eslint -- src/app/page.tsx src/app/person/'[id]'/page.tsx components/PeopleSidebar/PeopleSidebar.tsx components/PersonPortrait.tsx lib/api.ts
```

## Browser check with the backend running

1. Open `/` and compare the people tiles with `GET /people`. Confirm that one
   named and one unnamed person, if available, have the same IDs and labels as
   the API. An unnamed tile shows the suffix of its stable ID instead of a
   guessed name; its tooltip and link retain the complete ID.
2. Select each person. The URL must contain the saved ID, and the heading, ID,
   image, and facts must agree with `GET /people/{person_id}`. Supporting
   conversation appears only when its evidence record cites that same ID.
3. Reload a person URL directly. Navigate quickly between two different
   person URLs while delaying one request in browser developer tools. The page
   must never display the first person's data under the second person's URL.
4. Check a person with no facts and one with a missing face file. They should
   show the empty-facts message and portrait fallback respectively. A missing
   person URL should show the API error and a retry control.
5. If the API is temporarily unavailable, the sidebar and person page should
   show an error and allow retry after the API returns. If no one is enrolled,
   the sidebar should say so instead of displaying numbered placeholders.

Stage 4 changes only frontend reads and presentation. It has no database or
graph migration. The separate Stage 3 manual graph checkpoint remains required
before graph content is presented as a verified person connection.
