"""Runs Vault's tests, each in its own process (each needs its own QApplication), and summarises.

    python tests/run_all.py              all tests
    python tests/run_all.py health lock  only tests whose names contain one of these words
    python tests/run_all.py -v           show every test's output, not just failures

Set VAULT_TEST_NETWORK=1 to include the tests that download site icons.
Exit code 1 if any test failed.
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIMEOUT = 300


def main():
    args = sys.argv[1:]
    verbose = "-v" in args
    words = [a for a in args if a != "-v"]
    tests = sorted(p for p in HERE.glob("test_*.py") if not words or any(w in p.stem for w in words))
    work = Path(tempfile.mkdtemp(prefix="vault-tests-"))
    sys.path.insert(0, str(HERE))
    import fixtures
    fixtures.build(work)
    env = dict(os.environ, VAULT_TEST_WORK=str(work), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    print(f"{len(tests)} tests, working folder {work}\n", flush=True)
    failed, skipped, started = [], [], time.time()
    for test in tests:
        t = time.time()
        try:
            run = subprocess.run([sys.executable, str(test)], cwd=HERE.parent, env=env, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)
            out, code = run.stdout + run.stderr, run.returncode
        except subprocess.TimeoutExpired as exc:
            out, code = f"{exc.stdout or ''}\nTIMEOUT after {TIMEOUT}s", None
        lines = [l for l in out.splitlines() if l.strip() and "QFluentWidgets Pro" not in l]
        bad = code is None or any(re.match(r"\s*FAIL", l) for l in lines) or "Traceback" in out
        bad = bad or not any(re.match(r"\s*(OK|SKIP)", l) for l in lines)  # it must have checked something
        skip = next((l for l in lines if l.startswith("SKIP")), None)
        status = "FAIL" if bad else "skip" if skip else "ok"
        print(f"{status:5} {test.stem:28} {time.time() - t:5.1f}s" + (f"  ({skip[5:]})" if skip and not bad else ""),
              flush=True)
        if bad or verbose:
            print("      " + "\n      ".join(lines[-40:]) + "\n", flush=True)
        (failed if bad else skipped if skip else []).append(test.stem)
    print(f"\n{len(tests) - len(failed) - len(skipped)} passed, {len(skipped)} skipped, {len(failed)} failed "
          f"in {time.time() - started:.0f}s" + (f": {', '.join(failed)}" if failed else ""), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
