from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .kdb_runtime import build_q_subprocess_env, diagnose_kdb_runtime, run_q_script
from .parquet_schema import canonicalize_for_q_csv, classify_parquet_table


@dataclass(slots=True, frozen=True)
class LoadConfig:
    parquet_input_dir: Path
    hdb_root: Path
    q_exe: Path
    q_home: Path
    repo_root: Path
    duplicate_strategy: str = "skip"
    stage_dir: Path = Path("kdb/stage")
    keep_stage_csv: bool = False
    timeout_sec: int = 300


@dataclass(slots=True, frozen=True)
class LoadResult:
    table_name: str
    source_file: str
    row_count: int
    min_date: str | None
    max_date: str | None
    status: str
    q_stdout: str


def load_parquet_directory(config: LoadConfig) -> list[LoadResult]:
    diag = diagnose_kdb_runtime(
        q_exe=config.q_exe,
        license_file=config.q_home / "kc.lic",
        cwd=config.repo_root,
    )
    if not diag.q_startup_ok or not diag.test_expression_ok:
        raise RuntimeError(
            "kdb runtime diagnostics failed\n"
            f"startup={diag.startup}\n"
            f"expression={diag.expression}"
        )

    env = build_q_subprocess_env(q_home=config.q_home)
    _init_hdb(config=config, env=env)
    seen = _load_seen_manifest(config.hdb_root)
    discoveries = discover_parquet_files(config.parquet_input_dir)
    results: list[LoadResult] = []
    for table_name, parquet_path in discoveries:
        source_file = str(parquet_path.resolve())
        key = (table_name, source_file)
        if key in seen:
            if config.duplicate_strategy == "fail":
                raise RuntimeError(f"duplicate source detected: table={table_name} source={source_file}")
            results.append(
                LoadResult(
                    table_name=table_name,
                    source_file=source_file,
                    row_count=0,
                    min_date=None,
                    max_date=None,
                    status="skipped",
                    q_stdout="manifest_skip",
                )
            )
            continue
        row_count, min_date, max_date, csv_path = _stage_parquet_as_csv(
            parquet_path=parquet_path,
            table_name=table_name,
            stage_dir=config.stage_dir,
        )
        q_result = _load_csv_with_q(
            config=config,
            env=env,
            table_name=table_name,
            csv_path=csv_path,
            source_file=Path(source_file),
        )
        status = "loaded"
        results.append(
            LoadResult(
                table_name=table_name,
                source_file=source_file,
                row_count=row_count,
                min_date=min_date,
                max_date=max_date,
                status=status,
                q_stdout=q_result.stdout,
            )
        )
        _append_manifest(
            hdb_root=config.hdb_root,
            table_name=table_name,
            source_file=source_file,
            row_count=row_count,
            min_date=min_date,
            max_date=max_date,
        )
        if not config.keep_stage_csv:
            csv_path.unlink(missing_ok=True)
    return results


def discover_parquet_files(parquet_input_dir: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for path in sorted(parquet_input_dir.rglob("*.parquet")):
        table = classify_parquet_table(path)
        if table is None:
            continue
        out.append((table, path))
    return out


def summarize_results(results: list[LoadResult]) -> dict[str, object]:
    by_table: dict[str, dict[str, int]] = {}
    for item in results:
        bucket = by_table.setdefault(item.table_name, {"files": 0, "rows": 0, "loaded": 0, "skipped": 0})
        bucket["files"] += 1
        bucket["rows"] += item.row_count
        bucket[item.status] += 1
    return {"tables": by_table, "files": len(results)}


def _init_hdb(*, config: LoadConfig, env: dict[str, str]) -> None:
    script = config.repo_root / "q" / "init_hdb.q"
    result = run_q_script(
        q_exe=config.q_exe,
        q_script=script,
        args=[config.hdb_root.resolve().as_posix()],
        cwd=config.repo_root,
        env=env,
        timeout_sec=config.timeout_sec,
    )
    if result.returncode != 0:
        raise RuntimeError(f"init_hdb failed\nstdout={result.stdout}\nstderr={result.stderr}")


def _stage_parquet_as_csv(
    *,
    parquet_path: Path,
    table_name: str,
    stage_dir: Path,
) -> tuple[int, str | None, str | None, Path]:
    df = pd.read_parquet(parquet_path)
    normalized = canonicalize_for_q_csv(df, table_name)
    row_count = int(len(normalized))
    non_empty_dates = normalized["date"][normalized["date"] != ""]
    min_date = str(non_empty_dates.min()) if len(non_empty_dates) > 0 else None
    max_date = str(non_empty_dates.max()) if len(non_empty_dates) > 0 else None

    stage_dir.mkdir(parents=True, exist_ok=True)
    csv_path = stage_dir / table_name / f"{parquet_path.stem}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_csv(csv_path, index=False)
    return row_count, min_date, max_date, csv_path


def _load_csv_with_q(
    *,
    config: LoadConfig,
    env: dict[str, str],
    table_name: str,
    csv_path: Path,
    source_file: Path,
):
    script = config.repo_root / "q" / "load_table.q"
    result = run_q_script(
        q_exe=config.q_exe,
        q_script=script,
        args=[
            config.hdb_root.resolve().as_posix(),
            table_name,
            csv_path.resolve().as_posix(),
        ],
        cwd=config.repo_root,
        env=env,
        timeout_sec=config.timeout_sec,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "load_table failed\n"
            f"table={table_name}\n"
            f"source={source_file}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
    return result


def _load_seen_manifest(hdb_root: Path) -> set[tuple[str, str]]:
    path = _manifest_path(hdb_root)
    if not path.exists():
        return set()
    seen: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        seen.add((str(row["table_name"]), str(row["source_file"])))
    return seen


def _append_manifest(
    *,
    hdb_root: Path,
    table_name: str,
    source_file: str,
    row_count: int,
    min_date: str | None,
    max_date: str | None,
) -> None:
    path = _manifest_path(hdb_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "table_name": table_name,
        "source_file": source_file,
        "row_count": row_count,
        "min_date": min_date,
        "max_date": max_date,
        "status": "ok",
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _manifest_path(hdb_root: Path) -> Path:
    return hdb_root.parent / f"{hdb_root.name}_ingest_manifest.jsonl"


def results_to_json(results: list[LoadResult]) -> str:
    payload = {
        "results": [
            {
                "table_name": item.table_name,
                "source_file": item.source_file,
                "row_count": item.row_count,
                "min_date": item.min_date,
                "max_date": item.max_date,
                "status": item.status,
                "q_stdout": item.q_stdout,
            }
            for item in results
        ],
        "summary": summarize_results(results),
    }
    return json.dumps(payload, indent=2)

