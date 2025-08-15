# API_Calls.py
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional
from urllib.parse import urlencode
import os

# Optional: use PI Web API client if available, otherwise fall back to requests
try:
    from osisoft.pidevclub.piwebapi.pi_web_api_client import PIWebApiClient
except Exception:
    PIWebApiClient = None

import requests


@dataclass
class APIConfig:
    base_url: str                      # e.g., "https://your-pi-web-api-server/piwebapi"
    use_kerberos: bool = False
    username: Optional[str] = None
    password: Optional[str] = None
    timeout_seconds: int = 60          # for requests fallback


@dataclass
class APIParams:
    # Device selections (use API keys you want to send)
    substation: str = ""
    line: str = ""
    transformer: str = ""
    bus: str = ""
    feeder: str = ""

    # Date/time
    start_date: str = ""               # "YYYY-MM-DD"
    end_date: str = ""                 # "YYYY-MM-DD"
    interval_value: str = "0"          # numeric string
    interval_unit: str = "minute"      # "minute" or "hour"

    # Options
    datasets: List[str] = None         # ["Minimum", "Average", "Maximum"]
    output_unit: str = "Amp"
    coincidental_peaks: bool = False
    multi_phase: bool = False
    multi_phase_average: bool = False

    def to_query_dict(self) -> Dict[str, str]:
        """
        Convert params to a flat dict suitable for query strings/POST.
        Lists are joined as comma strings. Booleans become 'true'/'false'.
        Empty values are included only if you want to; here we exclude empties.
        """
        d = asdict(self)

        # Convert lists/bools
        if d.get("datasets") is None:
            d["datasets"] = ""
        else:
            d["datasets"] = ",".join(d["datasets"])

        for k, v in list(d.items()):
            if isinstance(v, bool):
                d[k] = "true" if v else "false"
            elif v is None:
                d[k] = ""

        # Optionally drop empty keys so the URL stays concise:
        d = {k: v for k, v in d.items() if str(v).strip() != ""}
        return d


def build_api_params(
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
) -> APIParams:
    # ensure numeric interval_value string
    iv = interval_value.strip()
    if not iv.isdigit():
        iv = "0"

    return APIParams(
        substation=device_params.get("substation", ""),
        line=device_params.get("line", ""),
        transformer=device_params.get("transformer", ""),
        bus=device_params.get("bus", ""),
        feeder=device_params.get("feeder", ""),
        start_date=start_date,
        end_date=end_date,
        interval_value=iv,
        interval_unit=(interval_unit or "minute"),
        datasets=datasets or [],
        output_unit=output_unit or "Amp",
        coincidental_peaks=bool(coincidental_peaks),
        multi_phase=bool(multi_phase),
        multi_phase_average=bool(multi_phase_average) if multi_phase else False,
    )


def compose_url(base_url: str, api_params: APIParams) -> str:
    """
    Compose a preview URL with query string appended.
    You might point this at a read-only preview endpoint or just show it.
    """
    q = urlencode(api_params.to_query_dict())
    # If your service expects e.g. base_url + "/streams/summary" etc., adjust here
    return f"{base_url}?{q}"


def make_pi_client(cfg: APIConfig):
    """
    Return a PIWebApiClient if available; else return None to use requests fallback.
    """
    if PIWebApiClient is None:
        return None
    return PIWebApiClient(
        cfg.base_url,
        useKerberos=cfg.use_kerberos,
        username=cfg.username,
        password=cfg.password
    )


def execute_query(cfg: APIConfig, api_params: APIParams) -> Tuple[int, str]:
    """
    Example executor. If PIWebApiClient is available, you'd use it to call your
    intended endpoints. Otherwise, a GET request fallback illustrates the pattern.

    Returns (status_code, text_or_error).
    """
    # Example endpoint: adjust this to the actual PI Web API route you need
    # For preview we just call base_url with query params via GET.
    query_dict = api_params.to_query_dict()

    if PIWebApiClient is not None:
        # Pseudo example with PIWebApiClient (adjust to your real calls)
        try:
            client = make_pi_client(cfg)
            # Example: call something via client (placeholder)
            # result = client.someApi.getSomething(query_dict)
            # return (200, str(result))
            # Since we don't know the exact method, we stub success:
            return (200, "PIWebApiClient connected successfully (stub). Provide concrete calls here.")
        except Exception as ex:
            return (500, f"PIWebApiClient error: {ex}")

    # Fallback: plain HTTP GET
    try:
        auth = None
        if not cfg.use_kerberos and cfg.username and cfg.password:
            auth = (cfg.username, cfg.password)

        r = requests.get(cfg.base_url, params=query_dict, auth=auth, timeout=cfg.timeout_seconds, verify=True)
        return (r.status_code, r.text)
    except Exception as ex:
        return (500, f"HTTP error: {ex}")


def build_preview_text(api_params: APIParams, full_url: str) -> str:
    return (
        "Selected parameters:\n"
        f"{api_params.to_query_dict()}\n\n"
        "Example REST query URL:\n"
        f"{full_url}"
    )
