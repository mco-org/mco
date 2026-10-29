from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
READ_STDIN = "import sys; sys.exit(0 if sys.stdin.readline() == '' else 1)"


class ProbeStdinTests(unittest.TestCase):
    def test_detection_probes_cannot_consume_the_callers_next_message(self) -> None:
        harness = """
import json
import sys
sys.path.insert(0, {root!r})
from runtime.adapters.ollama import OllamaAdapter
from runtime.adapters.shim import ShimAdapterBase
from runtime.contracts import CapabilitySet

class Probe(ShimAdapterBase):
    def _auth_check_command(self, binary):
        return [binary, '-c', {reader!r}]

if sys.argv[1] == 'ollama':
    ready = OllamaAdapter(model='fixture')._model_available(sys.executable)
else:
    adapter = Probe('codex', sys.executable, CapabilitySet([], False, False, False, False, '', []))
    ready, reason = adapter._probe_auth(sys.executable)
print(json.dumps({{'ready': ready, 'next_message': sys.stdin.readline()}}))
""".format(root=str(ROOT), reader=READ_STDIN)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "show").write_text(READ_STDIN, encoding="utf-8")
            for kind in ("shim", "ollama"):
                with self.subTest(kind=kind):
                    result = subprocess.run(
                        [sys.executable, "-c", harness, kind], cwd=tmp,
                        input="NEXT_MCP_MESSAGE\n", capture_output=True, text=True,
                        check=True, timeout=10,
                    )
                    payload = json.loads(result.stdout)
                    self.assertTrue(payload["ready"])
                    self.assertEqual(payload["next_message"], "NEXT_MCP_MESSAGE\n")
