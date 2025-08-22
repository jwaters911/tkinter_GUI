# Graphs.py
from __future__ import annotations
import io
import json
import hashlib
import tempfile
from dataclasses import asdict
from typing import Iterable, Optional, Tuple, List, Dict

import pandas as pd
import matplotlib.pyplot as plt

# Import your API layer
from API_Calls import (
    APIConfig, APIParams, build_api_params, compose_url,
    execute_query
)

# -----------------------------
# Public API
# -----------------------------

def fetch_to_dataframe(cfg: APIConfig, params: APIParams) -> pd.DataFrame:
    """
    Calls execute_query, parses the response (JSON preferred, CSV fallback),
    and returns a tidy DataFrame with columns:
        ['timestamp', 'tag', 'stat', 'value', 'unit']
    Only the columns found will be included; missing columns default sensibly.
    Raises ValueError on non-200 or empty/unsupported payloads.
    """
    status, text = execute_query(cfg, params)
    if status != 200:
        raise ValueError(f"API call failed: HTTP {status} - {text[:500]}")

    df = _parse_pi_response_to_df(text)

    if df.empty:
        raise ValueError("Parsed DataFrame is empty (no usable rows).")

    # If there is no explicit stat column but user requested datasets, attach one if possible.
    if 'stat' not in df.columns:
        ds = params.datasets or []
        if len(ds) == 1:
            df['stat'] = ds[0]
        elif len(ds) > 1:
            # Leave blank; caller can split files per dataset if API returns separate series
            df['stat'] = pd.NA

    # Ensure timestamp is datetime (if present)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df = df.dropna(subset=['timestamp']).sort_values('timestamp')

    # Attach unit if present in params (fallback)
    if 'unit' not in df.columns and getattr(params, 'output_unit', None):
        df['unit'] = params.output_unit

    # Normalize column order
    ordered_cols = [c for c in ['timestamp', 'tag', 'stat', 'value', 'unit'] if c in df.columns]
    rest = [c for c in df.columns if c not in ordered_cols]
    df = df[ordered_cols + rest]

    return df


def resample_timeseries(
    df: pd.DataFrame,
    interval: str,
    how: str = "mean",
    group_keys: Iterable[str] = ('tag', 'stat')
) -> pd.DataFrame:
    """
    Resample a tidy time series DataFrame by a pandas offset alias (e.g. '5min', '1H').
    Assumes 'timestamp' and 'value' columns.
    Groups by group_keys, then resamples value with aggregation method `how`.
    """
    if 'timestamp' not in df.columns or 'value' not in df.columns:
        return df.copy()

    if df.empty:
        return df.copy()

    gkeys = [k for k in group_keys if k in df.columns]
    if gkeys:
        out = []
        for keys, sub in df.groupby(gkeys):
            sub = sub.sort_values('timestamp').set_index('timestamp')
            if how == "sum":
                r = sub['value'].resample(interval).sum()
            elif how == "min":
                r = sub['value'].resample(interval).min()
            elif how == "max":
                r = sub['value'].resample(interval).max()
            else:
                r = sub['value'].resample(interval).mean()

            r = r.reset_index().rename(columns={'value': 'value'})
            # restore group columns
            if isinstance(keys, tuple):
                for k, v in zip(gkeys, keys):
                    r[k] = v
            else:
                r[gkeys[0]] = keys
            out.append(r)
        res = pd.concat(out, ignore_index=True)
        # Reorder
        ordered_cols = [c for c in ['timestamp', 'tag', 'stat', 'value', 'unit'] if c in res.columns]
        rest = [c for c in res.columns if c not in ordered_cols]
        return res[ordered_cols + rest].sort_values('timestamp')
    else:
        sub = df.sort_values('timestamp').set_index('timestamp')
        if how == "sum":
            r = sub['value'].resample(interval).sum()
        elif how == "min":
            r = sub['value'].resample(interval).min()
        elif how == "max":
            r = sub['value'].resample(interval).max()
        else:
            r = sub['value'].resample(interval).mean()
        return r.reset_index().rename(columns={'value': 'value'})


def plot_timeseries(
    df: pd.DataFrame,
    title: str = "PI Time Series",
    save_path: Optional[str] = None
) -> plt.Figure:
    """
    Simple matplotlib line plot of value vs timestamp.
    - If multiple 'tag' or 'stat' groups, draws one line per group.
    Returns the matplotlib Figure.
    """
    if df.empty:
        raise ValueError("Nothing to plot: DataFrame is empty.")

    if 'timestamp' not in df.columns or 'value' not in df.columns:
        raise ValueError("DataFrame needs 'timestamp' and 'value' columns to plot.")

    fig, ax = plt.subplots(figsize=(10, 5))

    group_cols = [c for c in ['tag', 'stat'] if c in df.columns]
    if group_cols:
        for keys, sub in df.groupby(group_cols):
            label = " - ".join([str(k) for k in (keys if isinstance(keys, tuple) else (keys,))])
            ax.plot(sub['timestamp'], sub['value'], label=label)
        ax.legend()
    else:
        ax.plot(df['timestamp'], df['value'])

    ax.set_xlabel("Timestamp")
    ax.set_ylabel(_pick_ylabel(df))
    ax.set_title(title)
    ax.grid(True)

    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=150)
    return fig


def cache_dataframe_parquet(df: pd.DataFrame, key_obj: Dict) -> str:
    """
    Saves the DataFrame to a Parquet file under the system temp directory.
    key_obj is hashed to create a stable cache filename (e.g., params dict).
    Returns the path to the saved file.
    """
    cache_key = hashlib.sha256(json.dumps(key_obj, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    path = f"{tempfile.gettempdir()}/pi_cache_{cache_key}.parquet"
    df.to_parquet(path, index=False)
    return path


# -----------------------------
# Helpers (internal)
# -----------------------------

def _parse_pi_response_to_df(text: str) -> pd.DataFrame:
    """
    Attempt to parse a PI Web API response into a tidy DataFrame.
    Tries JSON first; if that fails, tries CSV.
    This is intentionally flexible—you can tighten it once your exact shape is known.

    Supported JSON patterns (examples):
    1) {"Items":[{"Name":"tagA","Items":[{"Timestamp":"...","Value":1.2}, ...]}, ...]}
    2) {"Items":[{"Timestamp":"...","Value":1.2,"Name":"tagA","UnitsAbbreviation":"Amp"}, ...]}
    3) {"Timestamps":[...], "Values":[...], "Name":"tagA"}
    """
    # JSON first
    try:
        obj = json.loads(text)
        df = _parse_json_variants(obj)
        if not df.empty:
            return df
    except Exception:
        pass

    # CSV fallback
    try:
        df_csv = pd.read_csv(io.StringIO(text))
        # Try to infer columns
        cols = {c.lower(): c for c in df_csv.columns}
        ts_col = cols.get('timestamp') or cols.get('time') or cols.get('datetime')
        val_col = cols.get('value') or cols.get('values')
        tag_col = cols.get('tag') or cols.get('name') or cols.get('point')
        unit_col = cols.get('unit') or cols.get('units') or cols.get('unitsabbreviation')

        out = pd.DataFrame()
        if ts_col and val_col:
            out['timestamp'] = pd.to_datetime(df_csv[ts_col], errors='coerce')
            out['value'] = pd.to_numeric(df_csv[val_col], errors='coerce')
            if tag_col:
                out['tag'] = df_csv[tag_col].astype(str)
            if unit_col:
                out['unit'] = df_csv[unit_col].astype(str)
            out = out.dropna(subset=['timestamp'])
            return out
    except Exception:
        pass

    # If nothing matched, return empty
    return pd.DataFrame()


def _parse_json_variants(obj: dict) -> pd.DataFrame:
    # Variant 1: Items -> list of series, each with its own Items
    if isinstance(obj, dict) and isinstance(obj.get("Items"), list):
        # Detect nested items per tag
        if obj["Items"] and isinstance(obj["Items"][0], dict) and "Items" in obj["Items"][0]:
            frames = []
            for series in obj["Items"]:
                tag = series.get("Name") or series.get("Label") or series.get("Path") or series.get("WebId")
                unit = series.get("UnitsAbbreviation") or series.get("Unit")
                stat  = series.get("Stat") or series.get("SummaryType")  # sometimes summary calls return type
                items = series.get("Items") or []
                if isinstance(items, list) and items and isinstance(items[0], dict):
                    f = pd.DataFrame(items)
                    _rename_common_keys(f)
                    if 'timestamp' in f and 'value' in f:
                        f['tag'] = tag
                        if unit is not None and 'unit' not in f:
                            f['unit'] = unit
                        if stat is not None and 'stat' not in f:
                            f['stat'] = stat
                        frames.append(f[['timestamp', 'value'] + [c for c in ['tag','stat','unit'] if c in f.columns]])
            if frames:
                return pd.concat(frames, ignore_index=True)

        # Variant 2: flat Items with Timestamp/Value
        if obj["Items"] and isinstance(obj["Items"][0], dict):
            f = pd.DataFrame(obj["Items"])
            _rename_common_keys(f)
            keep = [c for c in ['timestamp','value','tag','stat','unit'] if c in f.columns]
            if {'timestamp','value'}.issubset(set(keep)):
                return f[keep]

    # Variant 3: paired arrays
    if all(k in obj for k in ('Timestamps','Values')) and isinstance(obj['Timestamps'], list):
        f = pd.DataFrame({'timestamp': obj['Timestamps'], 'value': obj['Values']})
        f['tag']  = obj.get('Name') or obj.get('Label') or obj.get('Path')
        if obj.get('UnitsAbbreviation'):
            f['unit'] = obj['UnitsAbbreviation']
        return f

    return pd.DataFrame()


def _rename_common_keys(df: pd.DataFrame) -> None:
    mapping = {}
    for c in df.columns:
        lc = c.lower()
        if lc in ('timestamp','time','datetime','localtimestamp','utcseconds'):
            mapping[c] = 'timestamp'
        elif lc in ('value','val','doublevalue','numericvalue'):
            mapping[c] = 'value'
        elif lc in ('name','tag','point','path','label'):
            mapping[c] = 'tag'
        elif lc in ('units','unit','unitsabbreviation'):
            mapping[c] = 'unit'
        elif lc in ('summarytype','stat','type'):
            mapping[c] = 'stat'
    if mapping:
        df.rename(columns=mapping, inplace=True)


def _pick_ylabel(df: pd.DataFrame) -> str:
    if 'unit' in df.columns and df['unit'].notna().any():
        unit = str(df['unit'].dropna().iloc[0])
        return f"Value ({unit})"
    return "Value"


# -----------------------------
# Example convenience entrypoint
# -----------------------------

def run_and_plot(
    cfg: APIConfig,
    device_params: Dict[str, str],
    start_date: str,
    end_date: str,
    interval_value: str,
    interval_unit: str,
    datasets: List[str],
    output_unit: str,
    coincidental_peaks: bool,
    multi_phase: bool,
    multi_phase_average: bool,
    resample_rule: Optional[str] = None,
    save_image_path: Optional[str] = None
) -> Tuple[pd.DataFrame, Optional[str]]:
    """
    Build params -> fetch -> normalize -> (optional) resample -> plot.
    Returns (df, parquet_cache_path or None).
    """
    params = build_api_params(
        device_params=device_params,
        start_date=start_date,
        end_date=end_date,
        interval_value=interval_value,
        interval_unit=interval_unit,
        datasets=datasets,
        output_unit=output_unit,
        coincidental_peaks=coincidental_peaks,
        multi_phase=multi_phase,
        multi_phase_average=multi_phase_average
    )
    df = fetch_to_dataframe(cfg, params)

    if resample_rule:
        df = resample_timeseries(df, resample_rule)

    # Optional: cache to Parquet using params as key
    parquet_path = cache_dataframe_parquet(df, asdict(params))

    plot_timeseries(df, title="PI Time Series", save_path=save_image_path)

    return df, parquet_path
