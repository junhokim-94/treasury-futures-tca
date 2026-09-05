from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.api.types import is_numeric_dtype

REQUIRED_MBO_EVENT_COLUMNS: tuple[str, ...] = (
    "date",
    "event_date",
    "ts_event_ns",
    "ts_recv_ns",
    "instrument_id",
    "raw_symbol",
    "action",
    "side",
    "order_id",
    "price_ticks",
    "size",
    "flags",
    "sequence",
)

REQUIRED_INSTRUMENT_DEF_COLUMNS: tuple[str, ...] = (
    "date",
    "instrument_id",
    "raw_symbol",
    "min_price_increment",
    "price_scale",
    "multiplier",
    "asset_class",
    "exchange",
    "expiry",
)

_MBO_NULLABLE_INT_COLUMNS = {"price_ticks", "size"}
_DEF_NULLABLE_DATE_COLUMNS = {"expiry"}


def classify_parquet_table(path: str | Path) -> str | None:
    table = _classify_from_schema_names(_read_parquet_schema_names(path))
    return table


def validate_dataframe_schema(df: pd.DataFrame, table_name: str) -> None:
    required = _required_columns(table_name)
    missing = [name for name in required if name not in df.columns]
    if missing:
        raise ValueError(f"{table_name}: missing required columns: {missing}")

    if table_name == "mbo_event":
        _validate_date_column(df["date"], "mbo_event.date")
        _validate_date_column(df["event_date"], "mbo_event.event_date")
        _validate_int_column(df["ts_event_ns"], "mbo_event.ts_event_ns")
        _validate_int_column(df["ts_recv_ns"], "mbo_event.ts_recv_ns")
        _validate_int_column(df["instrument_id"], "mbo_event.instrument_id")
        _validate_int_column(df["order_id"], "mbo_event.order_id")
        _validate_int_column(df["price_ticks"], "mbo_event.price_ticks", nullable=True)
        _validate_int_column(df["size"], "mbo_event.size", nullable=True)
        _validate_int_column(df["flags"], "mbo_event.flags")
        _validate_int_column(df["sequence"], "mbo_event.sequence")
        return

    if table_name == "instrument_def":
        _validate_date_column(df["date"], "instrument_def.date")
        _validate_int_column(df["instrument_id"], "instrument_def.instrument_id")
        _validate_float_column(df["min_price_increment"], "instrument_def.min_price_increment")
        _validate_int_column(df["price_scale"], "instrument_def.price_scale")
        _validate_float_column(df["multiplier"], "instrument_def.multiplier")
        _validate_date_column(df["expiry"], "instrument_def.expiry", nullable=True)
        return

    raise ValueError(f"unsupported table: {table_name}")


def canonicalize_for_q_csv(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    validate_dataframe_schema(df, table_name)
    required = _required_columns(table_name)
    out = pd.DataFrame()
    for name in required:
        series = df[name]
        if name in ("date", "event_date", "expiry"):
            nullable = table_name == "instrument_def" and name in _DEF_NULLABLE_DATE_COLUMNS
            out[name] = _normalize_date_text(series, nullable=nullable)
            continue
        if name in ("raw_symbol", "action", "side", "asset_class", "exchange"):
            out[name] = _normalize_text(series)
            continue
        if table_name == "mbo_event" and name in _MBO_NULLABLE_INT_COLUMNS:
            out[name] = _normalize_nullable_int_text(series)
            continue
        if table_name == "instrument_def" and name in ("min_price_increment", "multiplier"):
            out[name] = pd.to_numeric(series, errors="raise").astype("float64")
            continue
        out[name] = pd.to_numeric(series, errors="raise").astype("int64")
    return out


def _required_columns(table_name: str) -> tuple[str, ...]:
    if table_name == "mbo_event":
        return REQUIRED_MBO_EVENT_COLUMNS
    if table_name == "instrument_def":
        return REQUIRED_INSTRUMENT_DEF_COLUMNS
    raise ValueError(f"unsupported table: {table_name}")


def _read_parquet_schema_names(path: str | Path) -> set[str]:
    try:
        import pyarrow.parquet as pq  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pyarrow is required for parquet schema discovery") from exc
    schema = pq.read_schema(Path(path))
    return set(schema.names)


def _classify_from_schema_names(names: set[str]) -> str | None:
    has_mbo = set(REQUIRED_MBO_EVENT_COLUMNS).issubset(names)
    has_def = set(REQUIRED_INSTRUMENT_DEF_COLUMNS).issubset(names)
    if has_mbo and has_def:
        raise ValueError("ambiguous parquet schema: matches both mbo_event and instrument_def")
    if has_mbo:
        return "mbo_event"
    if has_def:
        return "instrument_def"
    return None


def _validate_int_column(series: pd.Series, label: str, *, nullable: bool = False) -> None:
    numeric = pd.to_numeric(series, errors="coerce")
    if not nullable and numeric.isna().any():
        raise ValueError(f"{label}: contains null/non-numeric values")
    if numeric.dropna().empty:
        return
    if not is_numeric_dtype(numeric):
        raise ValueError(f"{label}: not numeric")


def _validate_float_column(series: pd.Series, label: str) -> None:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.isna().all():
        raise ValueError(f"{label}: all values are null/non-numeric")


def _validate_date_column(series: pd.Series, label: str, *, nullable: bool = False) -> None:
    parsed = pd.to_datetime(series, errors="coerce")
    if not nullable and parsed.isna().any():
        raise ValueError(f"{label}: contains invalid date values")
    if parsed.dropna().empty and not nullable:
        raise ValueError(f"{label}: empty date column")


def _normalize_date_text(series: pd.Series, *, nullable: bool) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    if not nullable and parsed.isna().any():
        raise ValueError("date conversion failed")
    text = parsed.dt.strftime("%Y-%m-%d")
    return text.fillna("")


def _normalize_text(series: pd.Series) -> pd.Series:
    text = series.fillna("").astype(str)
    return text.where(text != "nan", "")


def _normalize_nullable_int_text(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    out = numeric.astype("Int64").astype(str)
    return out.where(~numeric.isna(), "")

