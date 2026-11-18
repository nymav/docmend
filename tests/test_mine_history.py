import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(repo, *a):
    subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)


class MineHistoryTests(unittest.TestCase):
    def test_flag_confirmed_by_later_human_fix_and_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            git(td, "init", "-q", "-b", "main"); git(td, "config", "user.email", "t@example.invalid"); git(td, "config", "user.name", "t")
            p = Path(td)
            def commit(msg, **files):
                for k, v in files.items():
                    (p / k).parent.mkdir(parents=True, exist_ok=True); (p / k).write_text(v)
                git(td, "add", "-A"); git(td, "commit", "-qm", msg)
            commit("base", **{"api.py": "def fetch(url, timeout=30):\n    return url\n",
                              "docs/api.md": "# API\n\nSignature: `fetch(url, timeout=30)`.\n\n## Other\n\nUnrelated.\n"})
            commit("code", **{"api.py": "def fetch(url, timeout=60):\n    return url\n"})
            commit("noise", **{"README.md": "# Readme\n"})
            commit("human fixes doc", **{"docs/api.md": "# API\n\nSignature: `fetch(url, timeout=60)`.\n\n## Other\n\nUnrelated.\n"})
            out = Path(td) / "out"
            r = subprocess.run([sys.executable, str(ROOT / "scripts/mine_history.py"), td, "--window", "5", "--output", str(out)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            s = json.loads((out / "summary.json").read_text())
            self.assertEqual((s["flagged_sections"], s["confirmed_by_later_human_edit"]), (1, 1))
            self.assertEqual((s["safe_fixes"], s["fixes_matching_human"]), (1, 1))
            self.assertEqual(s["baseline_later_edit_rate"], 0.0)  # "Other" was never edited
            row = json.loads((out / "cases.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["docmend_fix"], ["Signature: `fetch(url, timeout=60)`."])


if __name__ == "__main__":
    unittest.main()
