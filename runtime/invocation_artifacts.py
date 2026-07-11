from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence


class InvocationArtifactWriter:
    def __init__(self, root: Path, stage: str = "run") -> None:
        self.root = root
        self.stage = stage
        self.invocation_dir = root / "stages" / stage / "invocations"

    def start(self, invocation_id: str) -> Path:
        self.invocation_dir.mkdir(parents=True, exist_ok=True)
        path = self.invocation_dir / "{}.md".format(invocation_id)
        path.write_text("", encoding="utf-8")
        return path

    def append(self, path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()

    def write_run(
        self,
        *,
        task_id: str,
        status: str,
        exit_code: int,
        outputs: Sequence[Mapping[str, object]],
    ) -> None:
        result_parts = ["# MCO Run\n", "## Stage: {}\n".format(self.stage)]
        run_outputs = []
        for item in outputs:
            invocation_id = str(item.get("invocation_id", ""))
            provider = str(item.get("provider", ""))
            model = str(item.get("model", ""))
            invocation_status = str(item.get("status", "failed"))
            result_parts.append("### Invocation: {} ({}:{})\n".format(invocation_id, provider, model))
            if invocation_status == "success":
                result_parts.append(str(item.get("output", "")))
                result_parts.append("\n\n")
            else:
                result_parts.append("status: {}\n".format(invocation_status))
                error = item.get("error")
                if error:
                    result_parts.append("error: {}\n".format(error))
                result_parts.append("\n")
            run_outputs.append({
                "invocation_id": invocation_id,
                "provider": provider,
                "model": model,
                "status": invocation_status,
                "exit_code": item.get("exit_code"),
                "error": item.get("error"),
                "usage": item.get("usage"),
                "output_path": item.get("artifact_path"),
            })

        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "result.md").write_text("".join(result_parts), encoding="utf-8")
        (self.root / "run.json").write_text(
            json.dumps({
                "task_id": task_id,
                "stage": self.stage,
                "status": status,
                "exit_code": exit_code,
                "outputs": run_outputs,
            }, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
