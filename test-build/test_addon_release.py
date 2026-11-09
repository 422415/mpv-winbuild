"""Exercise release selection without GitHub writes or a native rebuild."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/mpv.yml").read_text()


def step(name):
    return re.search(r"(?ms)^      - name: " + re.escape(name) + r"\n(.*?)(?=^      - name:|\Z)", WORKFLOW)[1]


def render(script, values):
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", lambda m: str(values[m[1]]).lower()
                  if isinstance(values[m[1]], bool) else str(values[m[1]]), script)


def node(script, env=None):
    return subprocess.run(["node", "-e", script], text=True, capture_output=True,
                          env={**os.environ, **(env or {})})


class AddonReleaseTests(unittest.TestCase):
    def test_official_addon_release_is_allowed_but_fork_release_is_rejected(self):
        guards = textwrap.dedent(WORKFLOW.split("script: |\n", 1)[1].split("            const commit =", 1)[0])
        values = {"inputs.addon_metadata": True, "inputs.release": True,
                  "inputs.build_target": "64bit", "inputs.lgpl": False, "inputs.prs": ""}
        env = {"MPV_REPOSITORY": "the-database/mpv", "LIBASS_REPOSITORY": "the-database/libass"}
        def run():
            return node("const core = {setOutput() {}};\n" + render(guards, values), env)
        result = run()
        self.assertEqual(result.returncode, 0, result.stderr)
        for key in env:
            original = env[key]
            env[key] = "contributor/fork"
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Production releases require", result.stderr)
            values["inputs.release"] = False
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
            values["inputs.release"] = True
            env[key] = original

    def test_addon_tags_and_publish_settings_do_not_replace_normal_releases(self):
        script = textwrap.dedent(step("Get current time").split("script: |\n", 1)[1])
        release = step("Create release")
        expressions = {key: re.search(r"(?m)^          " + key + r": \$\{\{ (.*?) \}\}", release)[1]
                       for key in ("commit", "allowUpdates", "makeLatest")}
        for name in ("Commit version & remove existing tag", "Prune old releases"):
            expressions[name] = re.search(r"if: \$\{\{ (.*?) \}\}", step(name))[1]
        for addon, run_id in ((False, 99), (True, 99), (True, 100)):
            values = {"inputs.addon_metadata": addon, "github.run_id": run_id,
                      "needs.params.outputs.sha": "a" * 40}
            code = "globalThis.Date = class extends Date { constructor() { super('2026-11-03T12:34:00Z'); } };\n"
            code += "const output = {}; const core = {exportVariable(k,v) { output[k]=v; }};\n"
            code += render(script, values)
            code += "\nconst inputs = " + json.dumps({"addon_metadata": addon}) + "; const github = {sha:'workflow-source'};\n"
            for key, expression in expressions.items():
                code += "output[" + json.dumps(key) + "] = (" + expression + ");\n"
            result = node(code + "console.log(JSON.stringify(output));")
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = json.loads(result.stdout)
            expected_tag = "2026-11-03-aaaaaaaaaa" + (f"-addons-{run_id}" if addon else "")
            self.assertEqual(actual["tag_name"], expected_tag)
            self.assertEqual(actual["commit"], "workflow-source" if addon else "version")
            for key in ("allowUpdates", "makeLatest", "Commit version & remove existing tag", "Prune old releases"):
                self.assertEqual(actual[key], not addon, key)

    def test_normal_pruning_retains_pinned_addon_releases(self):
        tags = [(date(2026, 11, 3) - timedelta(days=i)).isoformat() + "-aaaaaaaaaa" for i in range(45)]
        addon = "2020-01-01-bbbbbbbbbb-addons-99"
        tags += [addon, tags[0] + "-addons-100"]
        # Substitute only Git/GitHub operations; run the actual pruning script.
        mocks = r'''
git() {
  case "$*" in
    'fetch --tags'|'push --tags --prune'|'checkout main') ;;
    'tag') printf '%s\n' "$AJN_TEST_TAGS" ;;
    'tag -d '*) ;;
    *) return 77 ;;
  esac
}
gh() { printf 'mock-gh %s\n' "$*"; }
source "$1"
'''
        bash = os.environ.get("AJN_TEST_BASH", "bash")
        env = {**os.environ, "AJN_TEST_TAGS": "\n".join(tags)}
        if Path(bash).is_absolute():
            env["PATH"] = str(Path(bash).parent) + os.pathsep + env.get("PATH", "")
        result = subprocess.run([bash, "-c", mocks, "fixture", (ROOT / "prunetags.sh").as_posix()],
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        deleted = [line.removeprefix("Deleting ") for line in result.stdout.splitlines() if line.startswith("Deleting ")]
        self.assertIn(tags[44], deleted)
        self.assertNotIn(tags[0], deleted)
        self.assertFalse(any("-addons-" in tag for tag in deleted))
        self.assertIn("Keep " + addon, result.stdout)


if __name__ == "__main__":
    unittest.main()
