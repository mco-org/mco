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

    def prepare(self) -> None:
        self.invocation_dir.mkdir(parents=True, exist_ok=True)
        for path in self.invocation_dir.glob("*.md"):
            path.unlink()

    def append(self, path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()

    @staticmethod
    def _append_invocation_result(result_parts: list[str], item: Mapping[str, object]) -> None:
        invocation_id = str(item.get("invocation_id", ""))
        provider = str(item.get("provider", ""))
        model = str(item.get("model", ""))
        invocation_status = str(item.get("status", "failed"))
        result_parts.append("### Invocation: {} ({}:{})\n".format(invocation_id, provider, model))
        if invocation_status == "success":
            result_parts.append(str(item.get("output", "")))
            result_parts.append("\n\n")
            return
        result_parts.append("status: {}\n".format(invocation_status))
        error = item.get("error")
        if error:
            result_parts.append("error: {}\n".format(error))
        result_parts.append("\n")

    @staticmethod
    def _run_output(item: Mapping[str, object]) -> dict[str, object]:
        run_output = {
            "invocation_id": str(item.get("invocation_id", "")),
            "provider": str(item.get("provider", "")),
            "model": str(item.get("model", "")),
            "status": str(item.get("status", "failed")),
            "exit_code": item.get("exit_code"),
            "error": item.get("error"),
            "output_path": item.get("artifact_path"),
        }
        if "usage" in item:
            run_output["usage"] = item["usage"]
        return run_output

    @staticmethod
    def _write_run_metadata(
        output_root: Path,
        *,
        task_id: str,
        stage: str,
        status: str,
        exit_code: int,
        outputs: Sequence[Mapping[str, object]],
    ) -> None:
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / "run.json").write_text(
            json.dumps({
                "task_id": task_id,
                "stage": stage,
                "status": status,
                "exit_code": exit_code,
                "outputs": [InvocationArtifactWriter._run_output(item) for item in outputs],
            }, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def write_run(
        self,
        *,
        task_id: str,
        status: str,
        exit_code: int,
        outputs: Sequence[Mapping[str, object]],
    ) -> None:
        result_parts = ["# MCO Run\n", "## Stage: {}\n".format(self.stage)]
        for item in outputs:
            self._append_invocation_result(result_parts, item)

        output_root = self.root if self.stage == "run" else self.root / "stages" / self.stage
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / "result.md").write_text("".join(result_parts), encoding="utf-8")
        self._write_run_metadata(
            output_root,
            task_id=task_id,
            stage=self.stage,
            status=status,
            exit_code=exit_code,
            outputs=outputs,
        )

    def write_root_run(
        self,
        *,
        task_id: str,
        status: str,
        exit_code: int,
        outputs: Sequence[Mapping[str, object]],
    ) -> None:
        grouped_outputs: dict[str, list[Mapping[str, object]]] = {}
        for item in outputs:
            stage = str(item.get("stage", "run"))
            grouped_outputs.setdefault(stage, []).append(item)
        ordered_stages = [stage for stage in grouped_outputs if stage != "synthesis"]
        if "synthesis" in grouped_outputs:
            ordered_stages.insert(0, "synthesis")

        result_parts = ["# MCO Run\n"]
        for stage in ordered_stages:
            result_parts.append("## Stage: {}\n".format(stage))
            for item in grouped_outputs[stage]:
                self._append_invocation_result(result_parts, item)

        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "result.md").write_text("".join(result_parts), encoding="utf-8")
        self._write_run_metadata(
            self.root,
            task_id=task_id,
            stage="run",
            status=status,
            exit_code=exit_code,
            outputs=outputs,
        )
