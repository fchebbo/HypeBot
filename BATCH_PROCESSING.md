# Batch Processing Feature — Implementation Brief

> **Status: not implemented.** This is a design brief only — there is no `/run-batch` route or
> `run_batch_pipeline` function in `server.py`, and no Batch tab in `templates/index.html`.
> HypeBot currently processes one VOD URL at a time. Treat everything below as a plan, not
> documentation of existing behavior.

## Note to developer

This is a self-contained feature addition. You have full access to the codebase and can implement this end-to-end without needing to loop in the channel owner. Read `server.py` and `templates/index.html` before starting so your implementation matches the existing patterns.

---

## What this feature does

Currently HypeBot processes one VOD at a time — paste a URL, hit Generate, wait. This feature allows the user to submit up to 5 URLs at once, then walk away while HypeBot downloads, scans, and cuts clips for all of them sequentially. When they come back, everything is ready to review.

---

## How it fits into the existing app

The existing single-URL pipeline in `server.py` is:

1. `POST /run` receives a URL
2. `run_pipeline(url, local_path)` runs in a background thread
3. Progress is streamed to the browser via `GET /logs` (Server-Sent Events)
4. When done, logs emit `__done__:[session_name]` which the UI picks up to load clips

Batch processing runs multiple `run_pipeline` calls **sequentially** (not in parallel) in a single background thread. Sequential is intentional — parallel downloads and FFmpeg jobs would saturate disk I/O and slow everything down.

---

## Implementation

### server.py changes

Add a new route `/run-batch` that accepts a list of URLs:

```python
@app.route("/run-batch", methods=["POST"])
def run_batch():
    data = request.get_json()
    urls = data.get("urls", [])
    urls = [u.strip() for u in urls if u.strip()]
    if not urls:
        return jsonify({"error": "No URLs provided"}), 400
    if len(urls) > 5:
        return jsonify({"error": "Maximum 5 URLs at once"}), 400
    threading.Thread(target=run_batch_pipeline, args=(urls,), daemon=True).start()
    return jsonify({"status": "started", "count": len(urls)})
```

Add the batch pipeline function:

```python
def run_batch_pipeline(urls):
    log(f"📋  Batch job started — {len(urls)} VOD(s) queued")
    for i, url in enumerate(urls):
        log(f"\n{'='*40}")
        log(f"📹  [{i+1}/{len(urls)}]  Starting: {url}")
        log(f"{'='*40}")
        run_pipeline(url, local_path='')
    log(f"\n🎉  Batch complete — all {len(urls)} VODs processed")
    log("__batch_done__")
```

Note: `run_pipeline` already emits `__done__:[session]` after each VOD — the UI can use this to progressively load sessions as they finish rather than waiting for the whole batch.

---

### index.html changes

Add a **Batch** tab alongside the existing URL and File tabs:

```
[ URL ]  [ FILE ]  [ BATCH ]
```

The Batch tab contains a simple form — a list of up to 5 URL inputs:

```
URL 1: [                                    ]
URL 2: [                                    ]
URL 3: [                                    ]
URL 4: [                                    ]
URL 5: [                                    ]

[ GENERATE BATCH ]
```

Empty fields are ignored — the user doesn't have to fill all 5.

On submit, collect non-empty URLs and POST to `/run-batch`. The existing log box and progress display work unchanged since they're driven by the same SSE stream.

When `__done__:[session]` fires mid-batch, load that session's clips into the review section immediately so the user can start reviewing the first VOD while the rest process.

When `__batch_done__` fires, show a banner: **"Batch complete — all VODs processed"**.

---

## Files to modify

| File | Change |
|------|--------|
| `server.py` | Add `/run-batch` route and `run_batch_pipeline` function |
| `templates/index.html` | Add Batch tab with multi-URL form |

No new files needed. No new dependencies.

---

## Things to watch out for

- **Sequential only** — do not run pipelines in parallel threads. FFmpeg + yt-dlp running simultaneously will cause slowdowns and potential file conflicts
- **Max 5 URLs** — enforced both client-side (only 5 inputs) and server-side (reject if > 5)
- **Empty field handling** — filter out blank inputs before sending to the server, don't send empty strings
- **Each VOD can take 20-60 minutes** — a 5 VOD batch could run for several hours. The SSE keepalive (`__keepalive__`) already handles long-running connections so the log stream won't time out
- **Existing `/run` route stays unchanged** — batch is additive, don't break the single URL flow
- **Error handling** — if one VOD in the batch fails, log the error and continue to the next one. Don't abort the whole batch
