from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(slots=True, frozen=True)
class QExecResult:
    cmd: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True, frozen=True)
class KDBRuntimeDiagnostics:
    q_executable_found: bool
    license_file_found: bool
    q_startup_ok: bool
    test_expression_ok: bool
    startup: QExecResult | None
    expression: QExecResult | None


def build_q_subprocess_env(*, q_home: Path, base_env: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if base_env is None else base_env
    out: dict[str, str] = dict(source)
    out.setdefault("QHOME", str(q_home))
    out.setdefault("QLIC", str(q_home))
    return out


def run_q_script(
    *,
    q_exe: Path,
    q_script: Path,
    args: list[str] | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout_sec: int = 180,
) -> QExecResult:
    cmd = [str(q_exe), str(q_script)]
    if args:
        cmd.extend(args)
    proc = subprocess.run(
        cmd,
        cwd=None if cwd is None else str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_sec,
    )
    return QExecResult(
        cmd=tuple(cmd),
        returncode=proc.returncode,
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
    )


def diagnose_kdb_runtime(
    *,
    q_exe: Path,
    license_file: Path,
    cwd: Path | None = None,
) -> KDBRuntimeDiagnostics:
    q_found = q_exe.exists()
    lic_found = license_file.exists()
    if not q_found:
        raise FileNotFoundError(f"q executable not found: {q_exe}")

    q_home = license_file.parent
    env = build_q_subprocess_env(q_home=q_home)
    workdir = Path.cwd() if cwd is None else cwd

    startup_script = _write_temp_q_script("0N!`startup_ok\n\\\\\n", workdir)
    expr_script = _write_temp_q_script("show 1+1\n\\\\\n", workdir)
    startup: QExecResult | None = None
    expr: QExecResult | None = None
    try:
        startup = run_q_script(
            q_exe=q_exe,
            q_script=startup_script,
            cwd=workdir,
            env=env,
            timeout_sec=60,
        )
        expr = run_q_script(
            q_exe=q_exe,
            q_script=expr_script,
            cwd=workdir,
            env=env,
            timeout_sec=60,
        )
    finally:
        startup_script.unlink(missing_ok=True)
        expr_script.unlink(missing_ok=True)

    q_startup_ok = startup.returncode == 0
    test_expression_ok = expr.returncode == 0 and "2" in expr.stdout
    return KDBRuntimeDiagnostics(
        q_executable_found=q_found,
        license_file_found=lic_found,
        q_startup_ok=q_startup_ok,
        test_expression_ok=test_expression_ok,
        startup=startup,
        expression=expr,
    )


def _write_temp_q_script(content: str, workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        suffix=".q",
        prefix="kdb_diag_",
        dir=str(workdir),
        delete=False,
        encoding="utf-8",
    ) as file:
        file.write(content)
        return Path(file.name)

