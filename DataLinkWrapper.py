from __future__ import annotations
import requests
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Union


# ---------- Exceptions ----------
class PIWebAPIError(Exception):
    """Base error for PI Web API issues."""


class PINotFound(PIWebAPIError):
    """Raised when a PI tag is not found."""


# ---------- Config ----------
@dataclass
class PIConfig:
    base_url: str                  # e.g., "https://yourserver/piwebapi"
    verify_ssl: bool = True
    # Choose ONE of the following auth modes:
    username: Optional[str] = None # For Basic or NTLM (DOMAIN\\user)
    password: Optional[str] = None
    use_ntlm: bool = False         # Requires requests-ntlm if True
    bearer_token: Optional[str] = None
    timeout_sec: int = 30


# ---------- Client (Tags only) ----------
class PIClient:
    """
    Lightweight PI Web API wrapper focused on PI *tags only* (no AF).

    DataLink-like methods:
      - arc_val(tag, time="*")
      - recorded(tag, start_time, end_time, boundary_type="Inside", max_points=None)
      - interpolated(tag, start_time, end_time, interval="1h")
      - summary(tag, start_time, end_time, summary_types=("Average",), calculation_basis="TimeWeighted",
                sample_interval=None, time_type="Auto")

    Notes:
      - Time strings: PI time (e.g., "*", "*-1d", "t-1h") or ISO8601.
      - Returns JSON objects as delivered by PI Web API.
    """

    def __init__(self, cfg: PIConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.verify = cfg.verify_ssl
        self.session.headers.update({"Accept": "application/json"})
        self.base = cfg.base_url.rstrip("/")

        # ---- Auth options ----
        if cfg.bearer_token:
            self.session.headers.update({"Authorization": f"Bearer {cfg.bearer_token}"})
        elif cfg.use_ntlm:
            try:
                from requests_ntlm import HttpNtlmAuth
            except Exception as e:
                raise PIWebAPIError("NTLM selected but 'requests-ntlm' not installed. pip install requests-ntlm") from e
            if not (cfg.username and cfg.password):
                raise PIWebAPIError("NTLM requires username='DOMAIN\\\\user' and password.")
            self.session.auth = HttpNtlmAuth(cfg.username, cfg.password)
        elif cfg.username and cfg.password:
            self.session.auth = (cfg.username, cfg.password)

    # ---- Low-level helpers ----
    def _get(self, url: str, **params) -> Dict[str, Any]:
        try:
            r = self.session.get(url, params=params, timeout=self.cfg.timeout_sec)
            if r.status_code == 404:
                raise PINotFound(f"Resource not found: {r.url}")
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            raise PIWebAPIError(f"HTTP error calling {url}: {e}") from e

    @lru_cache(maxsize=4096)
    def get_point_webid(self, tag: str) -> str:
        """
        Resolve PI tag -> point WebId using nameFilter.
        If multiple results, prefer exact (case-insensitive) name match.
        """
        url = f"{self.base}/points"
        data = self._get(url, nameFilter=tag)
        items = data.get("Items", [])
        if not items:
            raise PINotFound(f"Tag not found: {tag}")
        exact = [it for it in items if it.get("Name", "").lower() == tag.lower()]
        webid = (exact or items)[0].get("WebId")
        if not webid:
            raise PINotFound(f"No WebId for tag: {tag}")
        return webid

    # ---- DataLink-like methods ----
    def arc_val(self, tag: str, time: str = "*") -> Dict[str, Any]:
        """PIArcVal -> { 'Value': {... or scalar ...}, 'Timestamp': '...', 'Good': bool, ... }"""
        webid = self.get_point_webid(tag)
        url = f"{self.base}/streams/{webid}/value"
        return self._get(url, time=time)

    def recorded(
        self,
        tag: str,
        start_time: str,
        end_time: str,
        boundary_type: str = "Inside",
        max_points: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """PIRecorded/PISampDat -> list of events (Timestamp/Value)."""
        webid = self.get_point_webid(tag)
        url = f"{self.base}/streams/{webid}/recorded"
        params = {"startTime": start_time, "endTime": end_time, "boundaryType": boundary_type}
        if max_points:
            params["maxCount"] = max_points
        data = self._get(url, **params)
        return data.get("Items", [])

    def interpolated(
        self,
        tag: str,
        start_time: str,
        end_time: str,
        interval: str = "1h"
    ) -> List[Dict[str, Any]]:
        """PIInterpolated -> list of interpolated events at fixed interval."""
        webid = self.get_point_webid(tag)
        url = f"{self.base}/streams/{webid}/interpolated"
        data = self._get(url, startTime=start_time, endTime=end_time, interval=interval)
        return data.get("Items", [])

    def summary(
        self,
        tag: str,
        start_time: str,
        end_time: str,
        summary_types: Union[str, Iterable[str]] = ("Average",),
        calculation_basis: str = "TimeWeighted",        # 'TimeWeighted' | 'EventWeighted'
        sample_interval: Optional[str] = None,          # e.g., '1h' for interval rollups
        time_type: str = "Auto"                         # 'Auto'|'Local'|'UTC'
    ) -> Dict[str, Any]:
        """PISummary -> structured summary payload from PI Web API."""
        if isinstance(summary_types, str):
            summary_types = [summary_types]
        webid = self.get_point_webid(tag)
        url = f"{self.base}/streams/{webid}/summary"
        params = {
            "startTime": start_time,
            "endTime": end_time,
            "summaryType": ",".join(summary_types),
            "calculationBasis": calculation_basis,
            "timeType": time_type,
        }
        if sample_interval:
            params["sampleType"] = "Interval"
            params["intervals"] = sample_interval
        return self._get(url, **params)

    # ---- Convenience: list of events -> pandas.DataFrame ----
    @staticmethod
    def events_to_dataframe(events: List[Dict[str, Any]], value_field: str = "Value"):
        try:
            import pandas as pd
        except Exception as e:
            raise PIWebAPIError("pandas is required for events_to_dataframe(). pip install pandas") from e

        rows = []
        for it in events:
            ts = it.get("Timestamp")
            v = it.get(value_field)
            # Value may be nested dict with 'Value'
            if isinstance(v, dict) and "Value" in v:
                v = v["Value"]
            rows.append({"timestamp": ts, "value": v})
        df = pd.DataFrame(rows)
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.set_index("timestamp").sort_index()
        return df
