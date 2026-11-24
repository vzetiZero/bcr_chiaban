# -*- coding: utf-8 -*-
"""Kiểm cú pháp JS của mọi blob trong adapter bằng ``node --check``.

Selenium chỉ báo lỗi cú pháp khi script được chạy trên trang thật; một dấu
ngoặc sai trong blob sẽ chỉ hiện ra lúc chạy live. Script này bắt lỗi đó ngay
trong máy, cho cả ``aibcr/adapters/*.py`` (mọi hằng ``*_JS``).

    python tools/check_js_syntax.py            # toàn bộ adapter
    python tools/check_js_syntax.py ae888.py   # một file
"""

import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aibcr.adapters  # noqa: E402


def blobs(module, name):
    out = {}
    for attr in dir(module):
        if attr.endswith("_JS") or attr.endswith("_JS_RETURN"):
            value = getattr(module, attr)
            # ``READER_JS`` in ``browser`` is the *path* to ``reader.js``.
            if isinstance(value, str) and value.strip() and not value.lower().endswith(".js"):
                out["%s.%s" % (name, attr)] = value
    return out


# Some blobs are ``%``-format templates (``LIST_HASH_JS % json.dumps(...)``), so
# they are not valid JS until filled in. They are reported as skipped instead of
# failed — the goal is catching a broken brace in a literal script, not to
# re-implement Python's ``%`` formatting here.
_PLACEHOLDER = re.compile(r"%[sdr]|%\(")


def is_template(body):
    return bool(_PLACEHOLDER.search(body))


def main(argv):
    wanted = {arg if arg.endswith(".py") else arg + ".py" for arg in argv}
    files = sorted((ROOT / "aibcr" / "adapters").glob("*.py"))
    if wanted:
        files = [path for path in files if path.name in wanted]
    every = {}
    skipped = []
    for path in files:
        module = __import__("aibcr.adapters.%s" % path.stem,
                            fromlist=[path.stem])
        for key, body in blobs(module, path.stem).items():
            if is_template(body):
                skipped.append(key)
            else:
                every[key] = body
    if skipped:
        print("bỏ qua %d blob dùng %% -format: %s" % (len(skipped), ", ".join(skipped)))
    if not every:
        print("không tìm thấy blob JS nào")
        return 1
    script = ["const blobs = %s;" % json.dumps(every), """
let failed = 0;
for (const [name, body] of Object.entries(blobs)) {
  try {
    new Function(body);
    console.log('ok   ' + name);
  } catch (error) {
    failed += 1;
    console.log('FAIL ' + name + ' :: ' + error.message);
  }
}
console.log('total=' + Object.keys(blobs).length + ' failed=' + failed);
process.exitCode = failed ? 1 : 0;
"""]
    target = pathlib.Path(tempfile.gettempdir()) / "aibcr_js_syntax.cjs"
    target.write_text("\n".join(script), encoding="utf-8")
    result = subprocess.run(["node", str(target)], capture_output=True, text=True,
                            encoding="utf-8")
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip())
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
