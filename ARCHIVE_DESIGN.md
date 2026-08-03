# HypeBot Archive System — Design Doc

> **Status: implemented** in `server.py` (`/archive`, `/archive-list`, `/run-archive`,
> `/restore-venue`, `/archive-serve`, `/archive-thumb`) and `templates/archive.html`. This doc
> is kept close to current behavior; see the additions below for what shipped beyond the
> original design (dankify/replay/stitch archiving, and restore-by-venue).

## Concept

A permanent, curated export of only the best clips — replacing the old "archive session"
soft-hide feature entirely. The archive is the long-term library: source of truth for
upload-ready content, montage raw material, and eventually a direct TikTok/Reels upload pool.

After archiving and verifying, `clips/` and `downloads/` can be safely deleted to reclaim disk space.

---

## What Gets Archived

| Content | Included? |
|---|---|
| Vertical clip — flagged | ✅ |
| Vertical clip — has a final rendered (processed) | ✅ |
| Vertical clip — unflagged, no final | ❌ |
| Original 16:9 cut — same selection as above | ✅ / ❌ mirrors vertical |
| Finals (tier 1 renders with hook/text) | ✅ always |
| Montages | ✅ always |
| Dankify, Replay, and Stitch outputs | ✅ always (added post-launch — scanned by filename suffix from any session subfolder) |
| Session metadata (venue, source VOD URL) | ✅ always |

---

## Folder Structure

```
archive/
└── 2026-05/
    ├── meta.json
    ├── vertical/
    ├── original/
    ├── finals/
    ├── montages/
    ├── dankify/
    ├── replay/
    └── stitch/
```

Month folder named `YYYY-MM` by archive run date.
No session-level subfolders — month is the top-level grouping.
`meta.json` carries the venue/source association per clip.

---

## meta.json Schema

```json
{
  "archived_at": "2026-05-31",
  "clips": {
    "clip_1_3m12s_vertical.mp4": {
      "venue": "Kagaribi #16",
      "source": "https://youtube.com/watch?v=..."
    },
    "clip_2_5m44s_vertical.mp4": {
      "venue": "SoCal Local #5",
      "source": "https://..."
    }
  },
  "finals": {
    "clip_1_3m12s_final.mp4": {
      "venue": "Kagaribi #16",
      "source": "https://..."
    }
  },
  "montages": {
    "montage_1748123456.mp4": {
      "venue": "Kagaribi #16",
      "source": "https://..."
    }
  }
}
```

---

## /archive Page

- Separate endpoint — read-only, no render/edit controls
- Lists all month folders as tabs or sections
- Within a month: clips grouped by **venue** (read from meta.json)
- Each venue = collapsible section with clip cards (vertical preview, name, finals, montages)
- No session concept visible — venue is the organizing principle

---

## Archive Operation Flow

1. User navigates to `/archive` and hits **Run Archive**
2. System scans all active sessions in `clips/` (not `clips/archived/` — that concept is being removed)
3. Applies selection criteria: flagged clips, clips with finals, all montages
4. Shows a **preview summary**: N clips, N finals, N montages, estimated size
5. User confirms → files are **copied** (not moved) into `archive/YYYY-MM/`
6. User visually verifies `/archive` looks correct
7. User manually deletes `clips/` and `downloads/` when satisfied — never automatic

---

## Restore by Venue

Implemented at `POST /restore-venue` (not in the original design — added afterward). Given a
month and a venue name, copies every archived item tagged with that venue (clips, finals,
montages, dankify, replay, stitch) from `archive/YYYY-MM/` back into `clips/`, using each
item's meta.json entry to reconstruct the destination session/subfolder. Useful for pulling a
venue's material back out to build a new montage or hype reel from previously archived clips.

---

## What's Being Removed

The old "archive session" feature (soft-hide to `clips/archived/`):

- ARCHIVE button from the review UI
- Archived sessions collapsible section from the main page
- `/archive/<session>` POST endpoint
- `/unarchive/<session>` POST endpoint
- `archived` key from `/clips-list` response
- `renderArchived()` and `toggleArchived()` JS functions
- `archiveSession()` JS function

---

## Content Strategy Context

- **Tier 1 clips** — single clips with KO hook, rendered with text overlay. Daily posting floor.
- **Montages** — assembled from Tier 1 raw material (flagged clips). Higher effort, expected higher performance.
- The archive is the accumulating library of both. As the backlog grows, montage options multiply.
- Future: direct upload to TikTok / Instagram Reels from the archive page when the time is right.
