from __future__ import annotations

import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
import re
from dataclasses import dataclass
from pathlib import Path

MIN_PYTHON = (3, 10)
REPO_DIR = Path(__file__).resolve().parent
REQUIREMENTS_PATH = REPO_DIR / "requirements.txt"


@dataclass
class CheckResult:
    name: str
    required: str
    current: str
    status: str
    action: str


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True)


def parse_requirements(req_path: Path) -> list[tuple[str, str]]:
    requirements: list[tuple[str, str]] = []
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=!~]", line, maxsplit=1)[0].strip()
        requirements.append((name, line))
    return requirements


def version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for token in v.replace("-", ".").split("."):
        if token.isdigit():
            parts.append(int(token))
        else:
            num = ""
            for c in token:
                if c.isdigit():
                    num += c
                else:
                    break
            parts.append(int(num) if num else 0)
    return tuple(parts)


def match_spec(installed: str, spec: str) -> bool:
    installed_v = version_tuple(installed)
    for cond in [x.strip() for x in spec.split(",") if x.strip()]:
        if cond.startswith(">="):
            if installed_v < version_tuple(cond[2:]):
                return False
        elif cond.startswith(">"):
            if installed_v <= version_tuple(cond[1:]):
                return False
        elif cond.startswith("<="):
            if installed_v > version_tuple(cond[2:]):
                return False
        elif cond.startswith("<"):
            if installed_v >= version_tuple(cond[1:]):
                return False
        elif cond.startswith("=="):
            if installed_v != version_tuple(cond[2:]):
                return False
    return True


def check_python() -> CheckResult:
    current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    required = f">={MIN_PYTHON[0]}.{MIN_PYTHON[1]}"
    ok = (sys.version_info.major, sys.version_info.minor) >= MIN_PYTHON
    return CheckResult(
        name="python",
        required=required,
        current=current,
        status="OK" if ok else "FAIL",
        action="" if ok else "需要升級 Python",
    )


def attempt_install_python() -> str:
    system = platform.system().lower()
    candidates: list[list[str]] = []

    if system == "windows":
        if shutil.which("winget"):
            candidates.append(["winget", "install", "-e", "--id", "Python.Python.3.11"])
    elif system == "darwin":
        if shutil.which("brew"):
            candidates.append(["brew", "install", "python@3.11"])
    elif system == "linux":
        if shutil.which("apt-get"):
            candidates.append(["sudo", "apt-get", "update"])
            candidates.append(["sudo", "apt-get", "install", "-y", "python3.11", "python3.11-venv", "python3-pip"])

    if not candidates:
        return "找不到可用的自動安裝工具（winget/brew/apt-get）"

    for cmd in candidates:
        proc = run_cmd(cmd)
        if proc.returncode != 0:
            return f"自動安裝命令失敗：{' '.join(cmd)}\n{proc.stderr.strip() or proc.stdout.strip()}"
    return "Python 安裝命令已執行，請重新開啟終端機後再執行本腳本"


def ensure_pip_upgraded() -> tuple[bool, str]:
    proc = run_cmd([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    if proc.returncode == 0:
        return True, "pip 已更新"
    return False, (proc.stderr.strip() or proc.stdout.strip() or "pip 更新失敗")


def check_and_fix_packages(requirements: list[tuple[str, str]]) -> list[CheckResult]:
    results: list[CheckResult] = []

    for package_name, raw_spec in requirements:
        required_spec = raw_spec[len(package_name) :].strip()
        if not required_spec:
            required_spec = "(any)"

        try:
            current = importlib.metadata.version(package_name)
            ok = required_spec == "(any)" or match_spec(current, required_spec)
            if ok:
                results.append(CheckResult(package_name, required_spec, current, "OK", ""))
                continue
        except importlib.metadata.PackageNotFoundError:
            current = "not installed"

        install_proc = run_cmd([sys.executable, "-m", "pip", "install", "--upgrade", raw_spec])
        if install_proc.returncode == 0:
            try:
                new_version = importlib.metadata.version(package_name)
            except importlib.metadata.PackageNotFoundError:
                new_version = "unknown"
            results.append(CheckResult(package_name, required_spec, new_version, "FIXED", "已自動安裝/升級"))
        else:
            err = install_proc.stderr.strip() or install_proc.stdout.strip() or "安裝失敗"
            results.append(CheckResult(package_name, required_spec, current, "FAIL", err.splitlines()[-1]))

    return results


def print_results(results: list[CheckResult]) -> None:
    print("\n=== 環境檢查結果 ===")
    print(f"{'項目':<14} {'需求版本':<20} {'目前版本':<18} {'狀態':<8} 動作/訊息")
    print("-" * 90)
    for r in results:
        print(f"{r.name:<14} {r.required:<20} {r.current:<18} {r.status:<8} {r.action}")


def main() -> int:
    if not REQUIREMENTS_PATH.exists():
        print(f"找不到 requirements.txt：{REQUIREMENTS_PATH}")
        return 1

    all_results: list[CheckResult] = []

    py_result = check_python()
    all_results.append(py_result)

    if py_result.status != "OK":
        msg = attempt_install_python()
        py_result.action = msg
        print_results(all_results)
        print("\nPython 版本不符合需求，請完成 Python 安裝後重新執行本腳本。")
        return 1

    pip_ok, pip_msg = ensure_pip_upgraded()
    all_results.append(CheckResult("pip", ">=latest", "checked", "OK" if pip_ok else "FAIL", pip_msg))

    requirements = parse_requirements(REQUIREMENTS_PATH)
    pkg_results = check_and_fix_packages(requirements)
    all_results.extend(pkg_results)

    print_results(all_results)

    failed = [x for x in all_results if x.status == "FAIL"]
    if failed:
        print("\n有項目安裝失敗，請依訊息處理後重試。")
        return 1

    print("\n全部檢查通過，環境已可執行本專案。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
