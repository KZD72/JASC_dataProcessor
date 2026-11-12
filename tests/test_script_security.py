"""Reject hostile recordings and exercise isolated, file-scoped playback."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

import pandas as pd

from core.jobs import JobContext, JobCancelled
from core.script_jobs import ScriptRequest, run_script, worker_command
from core.script_language import Program, ScriptError
from core.script_runtime import Interpreter
from core.script_safety import FilePolicy
from core.workspace import Workspace
from jasc_api import Session


def recording(body: str) -> str:
    return 'from jasc_api import Session, series\n\ndef run(session):\n'+"\n".join("    "+line for line in body.splitlines())+"\n"


class ScriptSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.inputs, self.outputs = self.root/"input", self.root/"output"
        self.inputs.mkdir()
        self.outputs.mkdir()

    def request(self, body: str, **settings) -> ScriptRequest:
        return ScriptRequest(recording(body), self.inputs, self.outputs, **settings)

    def context(self, event: Event | None = None) -> JobContext:
        return JobContext(event or Event(), lambda _: None)

    def test_hostile_statements_and_object_escapes_are_rejected_before_execution(self):
        payloads = [
            'import os', 'from os import system', 'exec("print(1)")', 'eval("1")',
            '__import__("os").system("malicious")', 'open("bad.py", "w")',
            'session.__class__', 'session.__dict__', 'session.workspace',
            'x = session.__getattribute__("workspace")', 'session._editor(None)',
            'session = 1', 'series = 1', 'x = session', 'x = getattr(session, "sheet")',
            'session.foo()', 'session.new_sheet(**{})', 'session.new_sheet(*[])',
            'x = {**{}}', 'session.__class__ = 1', 'session.sheet = 1',
            'while True:\n    pass', 'x = [i for i in []]', 'x = (lambda: 1)()',
            'for x in range(100):\n    pass', 'try:\n    pass\nexcept:\n    pass',
            'x = "a" * 1000000000', 'x = 2 ** 1000000000',
            'x = ().__class__.__bases__[0].__subclasses__()',
            'x = session.new_sheet()\nx.frame.to_pickle("bad.pkl")',
            'x = session.new_sheet()\nx.frame.to_csv("bad.py")',
            'x = session.new_sheet()\nx.frame.__class__',
            'session.formula(None, output_column="x", expression="__import__(\'os\').system(\'bad\')")',
            'session.formula(None, output_column="x", expression="np.load(\'bad.pkl\', allow_pickle=True)")',
            'session.formula(None, output_column="x", expression="np.random.rand(999999999999)")',
            'session.fit(None, custom_models=[{"expression": "open(\'secret\').read()"}])',
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                source = recording('session.new_sheet(name="must not run")\n'+payload)
                with patch.object(Session, "new_sheet") as called:
                    with self.assertRaises(ScriptError):
                        Program.parse(source)
                    called.assert_not_called()

    def test_module_defaults_annotations_decorators_and_launcher_cannot_run_code(self):
        sources = [
            'import os\n'+recording('pass'),
            'open("bad", "w")\n'+recording('pass'),
            'def run(session=open("bad", "w")):\n    pass',
            'def run(session: open("bad", "w")):\n    pass',
            '@open("bad", "w")\ndef run(session):\n    pass',
            recording('pass')+'\nif __name__ == "__main__":\n    open("bad", "w")',
            recording('pass')+'\ndef run(session):\n    pass',
        ]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(ScriptError):
                Program.parse(source)
        good = recording('pass')+'\nif __name__ == "__main__":\n    session = Session.from_cli()\n    run(session)\n    session.finish()\n'
        self.assertFalse(Program.parse(good).commands)

    def test_source_size_depth_and_step_limits(self):
        with self.assertRaises(ScriptError):
            Program.parse("#"*(2*1024*1024+1))
        with self.assertRaises(ScriptError):
            Program.parse(recording("x = "+"["*200+"0"+"]"*200))
        interpreter = Interpreter(Session(), FilePolicy(self.inputs, self.outputs))
        interpreter.steps = 10_000
        with self.assertRaisesRegex(ScriptError, "step limit"):
            interpreter.run(Program.parse(recording("session.new_sheet()")))

    def test_file_read_scope_and_dangerous_output_names(self):
        files = FilePolicy(self.inputs, self.outputs)
        secret = self.root/"secret.csv"
        secret.write_text("x\n1\n", encoding="utf-8")
        for name in (str(secret), "../secret.csv", "https://example.test/data", r"\\server\share\data.csv", r"\\?\C:\secret.csv"):
            with self.subTest(path=name), self.assertRaises(ScriptError):
                files.read(name)
        for name in ("bad.py", "bad.exe", "bad.ps1", "bad.bat", "../bad.csv", "x.csv:bad", "CON.csv", "file.csv "):
            with self.subTest(path=name), self.assertRaises(ScriptError):
                files.write(name, {".csv"})
        destination = files.write(str(self.root/"elsewhere"/"good.csv"), {".csv"})
        self.assertEqual(destination, self.outputs/"good.csv")
        destination.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ScriptError, "overwrite"):
            files.write("good.csv", {".csv"})
        self.assertEqual(destination.read_text(), "keep")

    def test_symlinks_cannot_escape_the_input_folder(self):
        secret = self.root/"secret.csv"
        secret.write_text("x\n1\n", encoding="utf-8")
        link = self.inputs/"link.csv"
        try:
            link.symlink_to(secret)
        except OSError:
            self.skipTest("This Windows account cannot create file symlinks")
        with self.assertRaisesRegex(ScriptError, "escapes"):
            FilePolicy(self.inputs, self.outputs).read(str(link))
        with self.assertRaisesRegex(ScriptError, "escapes"):
            Interpreter(Session(), FilePolicy(self.inputs, self.outputs)).run(Program.parse(recording("sheets = session.load_folder('.')")))

    def test_repeat_blocks_use_bounded_worksheet_references(self):
        for index in range(2):
            pd.DataFrame({"x": [0., 1., 2.], "y": [1., 3., 5.]}).to_csv(self.inputs/f"data{index}.csv", index=False)
        session = Session()
        source = recording("for sheet in session.load_folder('.'):\n    report = session.statistics(sheet, operation_key='single_summary', primary_column='y', name=sheet.name+'_stats')")
        Interpreter(session, FilePolicy(self.inputs, self.outputs)).run(Program.parse(source))
        self.assertEqual(len(session.workspace.list_datasets()), 4)

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_windows_directory_junctions_cannot_escape_input_or_output_roots(self):
        outside = self.root/"outside"
        outside.mkdir()
        (outside/"secret.csv").write_text("x\n1\n", encoding="utf-8")
        for parent in (self.inputs, self.outputs):
            link = parent/"junction"
            created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                     capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(created.returncode, 0, created.stderr)
        policy = FilePolicy(self.inputs, self.outputs)
        with self.assertRaisesRegex(ScriptError, "escapes"):
            policy.read("junction/secret.csv")
        with self.assertRaises(ScriptError):
            policy.write("junction/escaped.csv", {".csv"})
        self.assertFalse((outside/"escaped.csv").exists())

    def test_real_worker_stages_data_exports_and_result_project(self):
        workspace = Workspace()
        original = workspace.add_dataset("source", pd.DataFrame({"x": [0., 1., 2.], "y": [2., 4., 6.]}))
        expected = original.frame.copy()
        request = self.request("sheet = session.sheet('source')\nsession.formula(sheet, output_column='twice', expression='col(\"y\")*2')\nsession.export_data(sheet, 'data.csv')")
        request = replace(request, source=request.source.replace("\n", "\r\n"))
        original_launch = subprocess.Popen
        def verify_bytes(command, **kwargs):
            script = Path(command[command.index("--script-worker")+1])
            self.assertEqual(script.read_bytes(), request.source.encode("utf-8"))
            return original_launch(command, **kwargs)
        with patch("core.script_jobs.subprocess.Popen", side_effect=verify_bytes):
            result = run_script(self.context(), request, workspace=workspace, publish=False)
        try:
            pd.testing.assert_frame_equal(original.frame, expected)
            self.assertTrue(result.folder.name.startswith(".jasc-script-ready-"))
            self.assertTrue((result.folder/"data.csv").is_file())
            self.assertEqual(result.workspace.get_dataset("source").frame.twice.tolist(), [4., 8., 12.])
            result.commit()
            self.assertTrue(result.folder.name.startswith("jasc_script_run_"))
            self.assertTrue((result.folder/"_jasc_result.jasc").is_file())
        finally:
            result.discard()

    def test_failed_run_discards_all_outputs_and_leaves_original_data_unchanged(self):
        workspace = Workspace()
        source = workspace.add_dataset("source", pd.DataFrame({"x": [1., 2.]}))
        request = self.request("sheet = session.sheet('source')\nsession.export_data(sheet, 'partial.csv')\nsession.sheet('missing')")
        with self.assertRaises(ScriptError):
            run_script(self.context(), request, workspace=workspace)
        self.assertEqual(list(self.outputs.iterdir()), [])
        self.assertEqual(source.frame.x.tolist(), [1., 2.])

    def test_timeout_terminates_the_actual_child_and_removes_staging(self):
        children = []
        original = subprocess.Popen
        def launch(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child
        with patch("core.script_jobs.subprocess.Popen", side_effect=launch):
            with self.assertRaisesRegex(ScriptError, "time limit"):
                run_script(self.context(), self.request("session.new_sheet()", timeout=0.1))
        self.assertTrue(children)
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(list(self.outputs.iterdir()), [])

    def test_cancellation_terminates_the_actual_child_and_removes_staging(self):
        cancellation = Event()
        original = subprocess.Popen
        children = []
        def launch(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            cancellation.set()
            return child
        with patch("core.script_jobs.subprocess.Popen", side_effect=launch):
            with self.assertRaises(JobCancelled):
                run_script(self.context(cancellation), self.request("session.new_sheet()"))
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(list(self.outputs.iterdir()), [])

    def test_source_entry_point_ignores_hostile_neighbor_modules(self):
        sentinel = self.inputs/"injected.txt"
        for name in ("jasc_api.py", "sitecustomize.py", "os.py"):
            (self.inputs/name).write_text(f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('injected')\n", encoding="utf-8")
        script = self.inputs/"recording.py"
        script.write_text(recording("session.new_sheet(name='result', rows=2)"), encoding="utf-8")
        output = self.outputs/"result.jasc"
        command = [sys.executable, "-B", str(Path(__file__).resolve().parents[1]/"main.py"), "--run-script", str(script), "--output", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.is_file())
        self.assertFalse(sentinel.exists())

    def test_frozen_command_uses_the_bundled_executable_not_external_python(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", "JASC.exe"):
            self.assertEqual(worker_command(), ["JASC.exe", "--script-worker"])

    def test_plot_styles_cannot_load_urls_files_modules_or_external_tex(self):
        from core.script_safety import validate_plot_settings
        for custom in ("https://example.test/style.mplstyle", str(self.inputs/"style.mplstyle"), "os.path"):
            with self.subTest(style=custom), self.assertRaises(ScriptError):
                validate_plot_settings({"style": {"custom": custom}})
        with self.assertRaisesRegex(ScriptError, "LaTeX"):
            validate_plot_settings({"style": {"use_latex": True}})
        validate_plot_settings({"style": {"preset": "science"}})

    def test_dangerous_saved_styles_are_rejected_before_other_commands_run(self):
        workspace = Workspace()
        workspace.add_plot("hostile", {"series": [], "settings": {"style": {"custom": "https://example.test/style"}}})
        session = Session(workspace)
        with self.assertRaises(ScriptError):
            Interpreter(session, FilePolicy(self.inputs, self.outputs)).run(Program.parse(recording("session.new_sheet()")))
        self.assertEqual(workspace.dataset_names(), [])


if __name__ == "__main__":
    unittest.main()
