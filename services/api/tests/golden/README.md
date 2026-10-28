# Golden snapshots

`orangehrm/`, `squoosh/`, `todomvc/`: the state of the three CAM jobs (`out/cam-*`) after the last
acceptance, enough to rerun the **script** step (T2) or the **produce** step (T1) with no LLM
and no browser. Used by `scripts/regress.py` (see CLAUDE.md, «Chính sách kiểm thử»).

| In git (`tests/golden/<name>/`) | Why |
|---|---|
| `confirmed_profile.json`, `outline_approved.json`, `selected_flow.json`, `flow_context.json` | input of the script step |
| `explore/pages/*.json` | page index the script / dedupe read (no pictures) |
| `flow/flow_approved.json`, `flow/flow_run.json`, `flow/live/logs.json` | the flow run and the logs of the live recording |
| `script_approved.json`, `script_report.json` (proof bank, critic), `theme*.json` | the approved script and its report |
| `produce/inventory/*.json` (frame_inventory), `produce/focus/*.json` (focus track + saved planner plan), `produce/render_props.json` | what the producer worked out |
| `report.json` | the original report (url, baseline numbers) |

**Not in git**: `tests/golden-media/<name>/` (`.gitignore`): `flow/live/flow.mp4` (the live clip),
`flow/steps/*`, `produce/*.mp4|png` and the final `video.mp4` (about 40 MB in all). Rebuild them from
the job dirs with `uv run python scripts/golden.py restore` (needs `out/cam-<name>/`); a fresh clone
without those job dirs has to take new snapshots (`golden.py build`, after a real run of the
three flows).

T1 replays the focus planner from the saved plans (`produce/focus/<scene>.json`), so even the one
LLM step of the producer is not called. Take new snapshots only when the upstream data changes on
purpose (a new acceptance), then `regress.py --tier t1 --save` to move the baseline.
