import pandas as pd
import pytest

from treasury_futures_execution_analytics_tca_engine.io.parquet_schema import canonicalize_for_q_csv, validate_dataframe_schema


def test_validate_mbo_event_schema_passes() -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-03-23"],
            "event_date": ["2026-03-23"],
            "ts_event_ns": [1],
            "ts_recv_ns": [2],
            "instrument_id": [42004475],
            "raw_symbol": ["ZNH6"],
            "action": ["ADD"],
            "side": ["B"],
            "order_id": [10],
            "price_ticks": [7250],
            "size": [5],
            "flags": [0],
            "sequence": [100],
        }
    )
    validate_dataframe_schema(df, "mbo_event")
    out = canonicalize_for_q_csv(df, "mbo_event")
    assert list(out.columns) == [
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
    ]


def test_validate_mbo_event_schema_missing_column_fails() -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-03-23"],
            "ts_event_ns": [1],
        }
    )
    with pytest.raises(ValueError):
        validate_dataframe_schema(df, "mbo_event")


def test_canonicalize_instrument_def_normalizes_dates_and_text() -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-03-23"],
            "instrument_id": [42004475],
            "raw_symbol": ["ZNH6"],
            "min_price_increment": [0.015625],
            "price_scale": [1000000000],
            "multiplier": [1000.0],
            "asset_class": ["RATE"],
            "exchange": ["CME"],
            "expiry": [None],
        }
    )
    out = canonicalize_for_q_csv(df, "instrument_def")
    assert out.loc[0, "date"] == "2026-03-23"
    assert out.loc[0, "expiry"] == ""
    assert out.loc[0, "raw_symbol"] == "ZNH6"

