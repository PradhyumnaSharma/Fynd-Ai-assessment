# utils/sheets_helper.py
"""
Robust Google Sheets helper (updated).

Key fix: supports Streamlit Secrets `st.secrets["gs_service"]` even when it's
not a plain dict (Streamlit returns a SecretDict/SecretStr wrappers). The loader
now accepts any mapping-like object from st.secrets and converts it to a plain dict.

Other behavior:
 - Priority: st.secrets['gs_service'] -> st.secrets['GSERVICE_JSON'] -> env GSERVICE_JSON -> gservice.json file
 - Reads GSHEET_ID from st.secrets or env or gsheet_id.txt
"""
import os
import json
import traceback
from typing import Any, Dict, Optional

import pandas as pd

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception as _e:
    gspread = None
    Credentials = None
    print("Warning: gspread/google oauth imports failed:", _e)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _st_secrets_get(key: str) -> Optional[Any]:
    try:
        import streamlit as st  # local import to avoid import-time dependency issues
        return st.secrets.get(key)
    except Exception:
        return None


def _env_get(key: str) -> Optional[str]:
    v = os.environ.get(key)
    return v if v else None


def _normalize_private_key(pk: Optional[str]) -> Optional[str]:
    if pk is None:
        return None
    # convert escaped newlines to real newlines if necessary
    if "\\n" in pk and "\n" not in pk:
        return pk.replace("\\n", "\n")
    return pk


def _convert_secret_to_dict(secret_obj: Any) -> Dict[str, Any]:
    """
    Convert Streamlit secret-like object to a plain dict.
    Accepts dict, Mapping, SecretDict, or any object with .items() or index access.
    """
    if secret_obj is None:
        return {}
    # already a dict
    if isinstance(secret_obj, dict):
        return dict(secret_obj)
    # mapping-like with items()
    items = getattr(secret_obj, "items", None)
    if callable(items):
        try:
            return dict(items())
        except Exception:
            pass
    # try attribute access for known keys
    try:
        keys = list(secret_obj.keys())
        return {k: secret_obj[k] for k in keys}
    except Exception:
        pass
    # last resort: attempt JSON roundtrip (Streamlit sometimes stores nested objects)
    try:
        return json.loads(json.dumps(secret_obj))
    except Exception:
        raise RuntimeError("Could not convert Streamlit secret object to dict; unsupported secret type.")


def _load_service_account_info() -> Dict[str, Any]:
    """
    Load service-account info into a dict suitable for Credentials.from_service_account_info(...)
    Priority:
      1) st.secrets['gs_service'] (table/dict-like)
      2) st.secrets['GSERVICE_JSON'] (string or dict)
      3) env GSERVICE_JSON (string)
      4) local gservice.json file
    """
    # 1) Streamlit table (preferred) - accept SecretDict or similar
    st_sa = _st_secrets_get("gs_service")
    if st_sa:
        try:
            sa = _convert_secret_to_dict(st_sa)
            if "private_key" in sa:
                sa["private_key"] = _normalize_private_key(sa["private_key"])
            return sa
        except Exception as e:
            raise RuntimeError(f"Found st.secrets['gs_service'] but failed to parse it: {e}")

    # 2) Streamlit GSERVICE_JSON (string or dict)
    st_json = _st_secrets_get("GSERVICE_JSON")
    if st_json:
        if isinstance(st_json, dict):
            sa = dict(st_json)
            if "private_key" in sa:
                sa["private_key"] = _normalize_private_key(sa["private_key"])
            return sa
        if isinstance(st_json, str):
            s = st_json.strip()
            if s.startswith('"""') and s.endswith('"""'):
                s = s[3:-3].strip()
            try:
                sa = json.loads(s)
                if "private_key" in sa:
                    sa["private_key"] = _normalize_private_key(sa["private_key"])
                return sa
            except Exception:
                try:
                    sa = json.loads(s.encode("utf-8").decode("unicode_escape"))
                    if "private_key" in sa:
                        sa["private_key"] = _normalize_private_key(sa["private_key"])
                    return sa
                except Exception:
                    raise RuntimeError("st.secrets['GSERVICE_JSON'] present but not valid JSON.")

    # 3) Environment variable GSERVICE_JSON
    env_json = _env_get("GSERVICE_JSON")
    if env_json:
        s = env_json.strip()
        if s.startswith('"""') and s.endswith('"""'):
            s = s[3:-3].strip()
        try:
            sa = json.loads(s)
            if "private_key" in sa:
                sa["private_key"] = _normalize_private_key(sa["private_key"])
            return sa
        except Exception:
            try:
                sa = json.loads(s.encode("utf-8").decode("unicode_escape"))
                if "private_key" in sa:
                    sa["private_key"] = _normalize_private_key(sa["private_key"])
                return sa
            except Exception:
                raise RuntimeError("GSERVICE_JSON env var present but not valid JSON.")

    # 4) local file fallback
    if os.path.exists("gservice.json"):
        try:
            with open("gservice.json", "r", encoding="utf8") as fh:
                sa = json.load(fh)
            if "private_key" in sa:
                sa["private_key"] = _normalize_private_key(sa["private_key"])
            return sa
        except Exception as e:
            raise RuntimeError(f"Failed to read local gservice.json: {e}")

    raise RuntimeError(
        "Service account JSON not found. Set GSERVICE_JSON env var (minified JSON) or add a 'gs_service' table "
        "or 'GSERVICE_JSON' in Streamlit secrets, or place gservice.json locally."
    )


def _get_gsheet_id() -> str:
    sid = _st_secrets_get("GSHEET_ID")
    if sid:
        return str(sid).strip()
    sid = _st_secrets_get("gsheet_id") or _st_secrets_get("gs_sheet_id")
    if sid:
        return str(sid).strip()
    sid = _env_get("GSHEET_ID") or _env_get("gsheet_id")
    if sid:
        return sid.strip()
    if os.path.exists("gsheet_id.txt"):
        with open("gsheet_id.txt", "r", encoding="utf8") as fh:
            data = fh.read().strip()
            if data:
                return data
    raise RuntimeError("GSHEET_ID not found in st.secrets, environment, or gsheet_id.txt")


def get_gspread_client():
    if gspread is None or Credentials is None:
        raise RuntimeError("Missing required libraries: ensure 'gspread' and 'google-auth' are installed.")

    try:
        sa_info = _load_service_account_info()
    except Exception as e:
        raise RuntimeError(f"Failed to load service account info: {e}")

    try:
        creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    except Exception as e:
        tb = traceback.format_exc()
        raise RuntimeError(f"Failed to create Credentials from service account info: {e}\n{tb}")

    try:
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        tb = traceback.format_exc()
        raise RuntimeError(f"Failed to authorize gspread client: {e}\n{tb}")


def _open_sheet():
    client = get_gspread_client()
    sheet_id = _get_gsheet_id()
    try:
        sh = client.open_by_key(sheet_id)
    except Exception as e:
        tb = traceback.format_exc()
        raise RuntimeError(f"Failed to open spreadsheet with id={sheet_id}: {e}\n{tb}")
    try:
        ws = sh.sheet1
    except Exception:
        raise RuntimeError("Spreadsheet opened but cannot access sheet1 (unexpected).")
    return ws


def sheet_to_df() -> pd.DataFrame:
    ws = _open_sheet()
    rows = ws.get_all_records()
    expected = ["id", "timestamp", "rating", "review", "ai_response", "ai_summary", "ai_actions"]
    if not rows:
        return pd.DataFrame(columns=expected)
    df = pd.DataFrame(rows)
    for c in expected:
        if c not in df.columns:
            df[c] = ""
    return df[expected]


def append_submission(row_dict: Dict[str, Any]) -> bool:
    ws = _open_sheet()
    header = ["id", "timestamp", "rating", "review", "ai_response", "ai_summary", "ai_actions"]
    try:
        existing = ws.row_values(1)
    except Exception:
        existing = []
    if not existing or existing[: len(header)] != header:
        try:
            ws.update("A1:G1", [header])
        except Exception:
            ws.insert_row(header, 1)
    row = [row_dict.get(k, "") for k in header]
    ws.append_row(row, value_input_option="USER_ENTERED")
    return True


def update_submission_by_id(sub_id: str, updates: Dict[str, Any]) -> bool:
    ws = _open_sheet()
    records = ws.get_all_records()
    if not records:
        return False
    header = ws.row_values(1)
    for idx, rec in enumerate(records, start=2):
        if str(rec.get("id")) == str(sub_id):
            for key, val in updates.items():
                if key in header:
                    col_index = header.index(key) + 1
                    ws.update_cell(idx, col_index, val)
            return True
    return False
