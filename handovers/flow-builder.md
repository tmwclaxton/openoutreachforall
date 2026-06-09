# Flow / sequence builder

**Status: ✅ Live. ⏳ Drag-and-drop reordering requested (not built yet).**

## What it does
HeyReach-style branching sequence builder in the **Flows** tab. Centred top-down tree
(CSS org-chart) with boxed step cards, icons, branch-condition pills (green Accepted/Replied,
red Not accepted/No reply), wait durations, and ⚑ End markers.

Step types: connect, message, inmail, wait, profile_visit, like_post, **end**, **blank**.
- **End** — stops the branch at runtime; steps below it are **kept dormant** (rendered greyed "paused · won't run"). Insert mid-branch to kill part of a flow.
- **Blank** — no-op pass-through. Flip a node **End ↔ Blank** to pause/resume a branch without deleting/rebuilding it.
- Per-node controls: **edit** (config), **Step type** dropdown (change what a step is; refuses changes that orphan a failure branch), **✕ remove** (splices the step out, reconnecting the branch).
- Editor textarea is large + grows on focus; **{ }** floating helper (bottom-right, Flows tab only) copies personalisation tags.
- Bar: create / **rename** / **duplicate** (deep-copies name + full tree) / delete (soft-archive) sequence.

## Personalisation tags that actually work
`{first_name}`, `{last_name}`, `{company}`, `{public_identifier}` (rendered by `executor._lead_context` + `render_template`). `{title}`/`{location}` are NOT wired yet (offered, not requested).

## ⏳ TODO — drag-and-drop (Archie requested)
"Make the flow drag and drop so I can move steps around." Not built. Approach when doing it:
HTML5 DnD on `.tnode` cards; drop targets = branch slots (each parent's success/failure
"insert" zones); a backend `api/step/<id>/move/` that re-parents (set `parent`, `branch`,
`order_in_branch`) with **cycle guard** (can't drop a node into its own subtree). Re-render via `loadSeq`.
Sizeable front-end change — scope before building.

## Key files
`linkedin/sequences/executor.py` (handlers incl. `_handle_end`/`_handle_blank`, `enroll_*`, pacing gate),
`linkedin/models.py` (`SequenceStep`, `StepType`), `linkedin/dashboard/views.py`
(`api_sequence*`, `api_create_step`, `api_update_step`, `api_delete_step`, `_STEP_DEFAULTS`),
`dashboard.html` (renderNode/nodeCard/renderTree/branchOpts/changeType/deleteStep). Migrations `0023` (end), `0025` (blank choice).
