"""Print steps_in_clip for finished core-flow jobs: python -m scripts.steps_in_clip <job-dir>..."""

import json
import sys
from pathlib import Path

from app.producer.steps_coverage import steps_in_clip
from app.schemas.generated.flow_run import FlowRun


def main(job_dirs: list[str]) -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    rows = {}
    for d in map(Path, job_dirs):
        run = FlowRun.model_validate_json((d / "flow" / "flow_approved.json").read_text("utf-8"))
        filmed = [m.i for m in run.live.marks] if run.live else []
        rows[d.name] = steps_in_clip(run, filmed)
    print(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
