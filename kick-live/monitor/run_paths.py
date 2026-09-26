#!/usr/bin/env python
"""run_paths.py -- resolve every runtime file from ONE RUN_DIR (stdlib only, Python 3.9).

Why: scripts/env.sh exports METRICS_FILE/CHAT_FILE/... from the RUN_DIR it saw at *source* time (the secrets-file
default, ~/.local/share/kick-live/run). A later `RUN_DIR=.../run-live python foo.py` then mixes two run dirs:
channel.json from run-live, metrics.jsonl from run/. That produced a false "Day 1" title on stream day 3
(scripts/set_title.py, 2026-09-26). Rule here: an env override such as $METRICS_FILE is honoured ONLY when it
lives under the resolved RUN_DIR; otherwise it is ignored (and the ignore is recorded for the decision output).

    from run_paths import RunPaths
    rp = RunPaths()                       # RUN_DIR from $RUN_DIR, else <repo>/run
    rp.metrics                            # $RUN_DIR/metrics.jsonl (or $METRICS_FILE when it is under RUN_DIR)
    rp.path("world.json")                 # any other file under RUN_DIR
    rp.ignored                            # {"METRICS_FILE": "/other/dir/metrics.jsonl"} when an override was dropped
    rp.describe()                         # dict for logs / --json output
"""
from __future__ import annotations

import os
from typing import Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)

# env var -> default basename under RUN_DIR (mirrors scripts/env.sh)
ENV_FILES = {
    "METRICS_FILE": "metrics.jsonl",
    "CHAT_FILE": "chat.jsonl",
    "ACTIVITY_FILE": "activity.jsonl",
    "STATE_FILE": "state.json",
}
ENV_DIRS = {
    "PID_DIR": "pids",
    "LOG_DIR": "logs",
}


def _under(path: str, root: str) -> bool:
    try:
        p = os.path.realpath(os.path.abspath(path))
        r = os.path.realpath(os.path.abspath(root))
    except (OSError, ValueError):
        return False
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


class RunPaths(object):
    def __init__(self, run_dir: Optional[str] = None, env: Optional[Dict[str, str]] = None):
        e = os.environ if env is None else env
        self.run_dir = os.path.abspath(run_dir or e.get("RUN_DIR") or os.path.join(REPO_ROOT, "run"))
        self.ignored: Dict[str, str] = {}
        self.honoured: Dict[str, str] = {}
        self._files: Dict[str, str] = {}
        for var, base in list(ENV_FILES.items()) + list(ENV_DIRS.items()):
            default = os.path.join(self.run_dir, base)
            override = e.get(var)
            if override and _under(override, self.run_dir):
                self._files[var] = os.path.abspath(override)
                if os.path.abspath(override) != default:
                    self.honoured[var] = os.path.abspath(override)
            else:
                if override:
                    self.ignored[var] = override
                self._files[var] = default

    # files
    @property
    def metrics(self) -> str:
        return self._files["METRICS_FILE"]

    @property
    def chat(self) -> str:
        return self._files["CHAT_FILE"]

    @property
    def activity(self) -> str:
        return self._files["ACTIVITY_FILE"]

    @property
    def state(self) -> str:
        return self._files["STATE_FILE"]

    @property
    def pid_dir(self) -> str:
        return self._files["PID_DIR"]

    @property
    def log_dir(self) -> str:
        return self._files["LOG_DIR"]

    def path(self, basename: str) -> str:
        return os.path.join(self.run_dir, basename)

    def describe(self) -> Dict[str, object]:
        d: Dict[str, object] = {"run_dir": self.run_dir, "metrics": self.metrics, "chat": self.chat,
                                "pid_dir": self.pid_dir, "log_dir": self.log_dir}
        if self.ignored:
            d["env_overrides_ignored_outside_run_dir"] = dict(self.ignored)
        if self.honoured:
            d["env_overrides_honoured"] = dict(self.honoured)
        return d


def self_test() -> int:
    import tempfile
    fails = []
    with tempfile.TemporaryDirectory() as td:
        live = os.path.join(td, "run-live")
        other = os.path.join(td, "run")
        os.makedirs(live)
        os.makedirs(other)
        # 1. the env.sh trap: RUN_DIR=run-live but METRICS_FILE points at run/
        rp = RunPaths(env={"RUN_DIR": live, "METRICS_FILE": os.path.join(other, "metrics.jsonl"),
                           "PID_DIR": os.path.join(other, "pids")})
        if rp.metrics != os.path.join(live, "metrics.jsonl"):
            fails.append("outside override not ignored: %s" % rp.metrics)
        if rp.pid_dir != os.path.join(live, "pids"):
            fails.append("PID_DIR outside override not ignored: %s" % rp.pid_dir)
        if set(rp.ignored) != {"METRICS_FILE", "PID_DIR"}:
            fails.append("ignored set wrong: %r" % rp.ignored)
        # 2. an override under RUN_DIR is honoured
        rp = RunPaths(env={"RUN_DIR": live, "METRICS_FILE": os.path.join(live, "sub", "m.jsonl")})
        if rp.metrics != os.path.join(live, "sub", "m.jsonl") or rp.ignored:
            fails.append("inside override not honoured: %s %r" % (rp.metrics, rp.ignored))
        # 3. prefix trick: /tmp/run-live-evil is not under /tmp/run-live
        rp = RunPaths(env={"RUN_DIR": live, "METRICS_FILE": live + "-evil/metrics.jsonl"})
        if rp.metrics != os.path.join(live, "metrics.jsonl"):
            fails.append("prefix trick accepted: %s" % rp.metrics)
        # 4. no env at all -> <repo>/run
        rp = RunPaths(env={})
        if rp.run_dir != os.path.join(REPO_ROOT, "run"):
            fails.append("default run dir: %s" % rp.run_dir)
        # 5. explicit run_dir argument wins over env
        rp = RunPaths(run_dir=other, env={"RUN_DIR": live})
        if rp.run_dir != other or rp.chat != os.path.join(other, "chat.jsonl"):
            fails.append("explicit run_dir lost: %s" % rp.run_dir)
    for f in fails:
        print("run_paths SELF-TEST FAIL: %s" % f)
    print("run_paths self-test %s (5 checks)" % ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    import sys
    sys.exit(self_test())
