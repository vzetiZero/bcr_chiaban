# -*- coding: utf-8 -*-
"""Kiểm thử kiến trúc: giữ dự án đúng MVC và không quay lại tkinter.

Luật được kiểm bằng AST (không cần chạy app, không cần Chrome):

    Model      -> không import tkinter/selenium/websocket, không import tầng trên
    Adapter    -> không import Controller/Service
    Controller -> không import Service (Service gọi Controller, không ngược lại)
    Service    -> chỉ là transport JSON-RPC, không chứa nghiệp vụ
    Toàn repo  -> không còn import tkinter, không còn package ``aibcr.views``

Ngoài ra chặn Đua ngựa quay lại (không còn ``race``/``horse`` trong mã).
"""

import ast
import importlib
import inspect
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "aibcr"

FORBIDDEN_FOR_MODEL = ("tkinter", "selenium", "websocket")
UPSTREAM_OF_MODEL = ("aibcr.adapters", "aibcr.controllers", "aibcr.service")


def module_files(layer):
    return sorted((PKG / layer).glob("*.py"))


def source_files(*folders):
    files = []
    for folder in folders:
        files.extend(sorted((ROOT / folder).rglob("*.py")))
    return files


def imported_names(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names.append(base)
            names.extend("%s.%s" % (base, alias.name) for alias in node.names)
    return names


def defined_names(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return names


def matches(name, prefixes):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


class LayerDependencyTests(unittest.TestCase):
    def test_models_are_pure_logic(self):
        for path in module_files("models"):
            names = imported_names(path)
            for forbidden in FORBIDDEN_FOR_MODEL:
                self.assertFalse(any(matches(name, (forbidden,)) for name in names),
                                 "%s: Model không được import %s" % (path.name, forbidden))
            for upstream in UPSTREAM_OF_MODEL:
                self.assertFalse(any(matches(name, (upstream,)) for name in names),
                                 "%s: Model không được import %s" % (path.name, upstream))

    def test_adapters_do_not_depend_on_controllers_or_service(self):
        for path in module_files("adapters"):
            names = imported_names(path)
            self.assertFalse(any(matches(name, ("aibcr.controllers", "aibcr.service"))
                                 for name in names),
                             "%s: Adapter chỉ được dùng Model/config" % path.name)

    def test_controllers_do_not_import_the_transport(self):
        for path in module_files("controllers"):
            names = imported_names(path)
            self.assertFalse(any(matches(name, ("aibcr.service",)) for name in names),
                             "%s: Controller không được import tầng transport" % path.name)

    def test_controllers_are_the_composition_root(self):
        """Controller là nơi duy nhất nối Model + Adapter."""
        names = set()
        for path in module_files("controllers"):
            names.update(imported_names(path))
        for expected in ("aibcr.models", "aibcr.adapters"):
            self.assertTrue(any(matches(name, (expected,)) for name in names),
                            "thiếu import %s trong tầng Controller" % expected)

    def test_service_is_a_thin_transport(self):
        path = PKG / "service/engine.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
        self.assertIn("main", functions)
        self.assertIn("build_service", functions)
        self.assertIn("Emitter", classes)
        # Không được định nghĩa controller/luật cầu trong tầng transport.
        self.assertEqual([name for name in classes if name != "Emitter"], [])
        self.assertLess(len(path.read_text(encoding="utf-8").splitlines()), 200,
                        "engine.py chỉ nên là transport mỏng")


class NoTkinterAnymoreTests(unittest.TestCase):
    def test_no_python_file_imports_tkinter(self):
        checked = 0
        for path in source_files("aibcr", "tests", "tools"):
            names = imported_names(path)
            checked += 1
            self.assertFalse(any(matches(name, ("tkinter",)) for name in names),
                             "%s còn import tkinter" % path.relative_to(ROOT))
        self.assertGreater(checked, 10)

    def test_views_package_is_gone(self):
        self.assertFalse((PKG / "views").exists(), "giao diện phải nằm ở ui/ (Electron)")
        self.assertFalse((ROOT / "app.py").exists(), "không còn entry tkinter ở gốc")

    def test_root_has_no_compatibility_shims(self):
        for shim in ("browser.py", "engine.py", "lobby_stream.py", "method.py",
                     "money.py", "table_bets.py", "human_mouse.py", "ghost_mouse.py",
                     "mouse_chromedriver.py"):
            self.assertFalse((ROOT / shim).exists(), "%s phải dùng aibcr.* trực tiếp" % shim)


class StructureTests(unittest.TestCase):
    def test_mvc_modules_are_present(self):
        for rel in ("aibcr/config.py", "aibcr/__main__.py",
                    "aibcr/models/money.py", "aibcr/models/live_sim.py",
                    "aibcr/adapters/browser.py", "aibcr/adapters/lobby_stream.py",
                    "aibcr/adapters/table_bets.py",
                    "aibcr/controllers/baccarat.py",
                    "aibcr/service/engine.py",
                    "README.md"):
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_method_module_and_backtest_are_gone(self):
        self.assertFalse((ROOT / "aibcr/models/method.py").exists(),
                         "không còn phương pháp 3-3/3-2")
        self.assertFalse((ROOT / "tools/backtest.py").exists(),
                         "không còn script backtest của phương pháp cũ")

    def test_electron_ui_files_are_present(self):
        for rel in ("ui/package.json", "ui/main.js", "ui/preload.js",
                    "ui/renderer/index.html", "ui/renderer/app.js", "ui/renderer/styles.css"):
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_games_use_a_single_baccarat_profile(self):
        from aibcr.service import engine

        self.assertEqual(sorted(engine.GAMES), ["baccarat"])
        port, profile, state = engine.GAMES["baccarat"]
        self.assertEqual(port, 9222)
        self.assertEqual(profile, "chrome_profile")
        self.assertEqual(state, "aibcr_state_baccarat.json")

    def test_main_module_exposes_the_engine_entry(self):
        text = (PKG / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("from aibcr.service.engine import main", text)


class ControllerApiTests(unittest.TestCase):
    def test_the_controller_exposes_dispatch_and_snapshot(self):
        for module_name, class_name in (("aibcr.controllers.baccarat", "BaccaratController"),):
            module = importlib.import_module(module_name)
            controller = getattr(module, class_name)
            self.assertTrue(callable(getattr(controller, "dispatch", None)),
                            "%s thiếu dispatch()" % class_name)
            self.assertTrue(callable(getattr(controller, "snapshot", None)),
                            "%s thiếu snapshot()" % class_name)
            self.assertFalse(any(matches(name, ("tkinter",))
                                 for name in imported_names(pathlib.Path(module.__file__))),
                             "%s không được import tkinter" % class_name)

    def test_engine_keeps_the_legacy_class_alias(self):
        from aibcr.service import engine

        self.assertIs(engine.BaccaratService, engine.BaccaratController)

    def test_dispatch_reports_unknown_methods_without_raising(self):
        import pathlib as _path
        import tempfile

        from aibcr.controllers.baccarat import BaccaratController

        class Emitter:
            def event(self, name, data):
                pass

        controller = BaccaratController(_path.Path(tempfile.mkdtemp()) / "s.json", Emitter())
        result, error = controller.dispatch("khong.ton.tai", {})
        self.assertIsNone(result)
        self.assertIn("không hỗ trợ", error)


class ElectronWiringTests(unittest.TestCase):
    def test_ui_never_touches_python_directly(self):
        """Renderer chỉ nói chuyện qua preload/contextBridge, không spawn tiến trình."""
        renderer = (ROOT / "ui/renderer/app.js").read_text(encoding="utf-8")
        self.assertNotIn("require('child_process')", renderer)
        self.assertNotIn("spawn(", renderer)
        preload = (ROOT / "ui/preload.js").read_text(encoding="utf-8")
        self.assertIn("contextBridge.exposeInMainWorld", preload)
        main = (ROOT / "ui/main.js").read_text(encoding="utf-8")
        self.assertNotIn("nodeIntegration: true", main)
        self.assertIn("aibcr.service.engine", main, "main.js spawn engine qua -m aibcr.service.engine")


class NoHorseRacingLeftoversTests(unittest.TestCase):
    """Đua ngựa và LONG-LONG không còn trong ChiaBanBCR."""

    PATTERNS = (
        r"\bimport race\b", r"\bfrom aibcr\.models import race\b", r"\brace\.",
        r"\bRaceStrategy\b", r"\bRaceSimulation\b", r"\bRacePanelMixin\b",
        r"\bdecode_race_results\b", r"\bsweep_race\b", r"\bread_race_results\b",
        r"\bGAME_RACE\b", r"\braceGrids\b", r"\b_build_horse_panel\b", r"_race_saved",
        r"rng-racetrack", r"\brace_ladder\b", r"\brace_base\b",
        r"\bLongLongController\b", r"\bLongLongSimulation\b", r"\bdecode_longlong_results\b",
        r"\bGAME_LONGLONG\b", r"\bsweep_longlong\b", r"\bread_longlong_results\b",
    )

    def test_no_race_symbols_in_python_or_js(self):
        files = [p for p in list(ROOT.glob("*.py")) + list(PKG.rglob("*.py"))
                 + list((ROOT / "tests").rglob("*.py")) + list((ROOT / "tools").rglob("*.py"))
                 if p != pathlib.Path(__file__)]
        files += list(PKG.rglob("*.js")) + list((ROOT / "ui").rglob("*.js"))
        for path in files:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            for pattern in self.PATTERNS:
                self.assertIsNone(re.search(pattern, text),
                                  "%s còn sót %r" % (path.relative_to(ROOT), pattern))


if __name__ == "__main__":
    unittest.main(verbosity=2)
