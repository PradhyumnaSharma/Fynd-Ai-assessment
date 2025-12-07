# utils/sheets_helper.py
"""
Google Sheets helper (drop-in).
Reads service-account credentials directly from Streamlit secrets table `[gs_service]`
(or fallback to GSERVICE_JSON env / st.secrets['GSERVICE_JSON'] / local gservice.json).
Also reads GSHEET_ID from st.secrets['GSHEET_ID'] or env GSHEET_ID (or gsheet_id.txt fallback).

Public functions:
- get_gspread_client()
- sheet_to_df() -> pandas.DataFrame
- append_submission(row_dict)
- update_submission_by_id(sub_id, updates)

Expected secrets.toml (example):
[gs_service]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = """-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----
"""
client_email = "..."
...
GSHEET_ID = "sheet-id"
GEMINI_API_KEY = "..."
"""
from typing import Any, Dict, Optional
import os
import json

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _st_secrets_get(key: str) -> Optional[Any]:
    """
    Safe read from streamlit secrets (returns None if streamlit not present or key missing).
    """
    try:
        import streamlit as st
        return st.secrets.get(key)
    except Exception:
        return None


def _env_get(key: str) -> Optional[str]:
    v = os.environ.get(key)
    return v if v else None


def _normalize_private_key(pk: Optional[str]) -> Optional[str]:
    if pk is None:
        return None
    # If the key contains escaped newlines but not real ones, convert them.
    if "\\n" in pk and "\n" not in pk:
        return pk.replace("\\n", "\n")
    return pk


def _load_service_account_info() -> Dict[str, Any]:
    """
    Load service account info in this order:
      1) st.secrets['gs_service'] (TOML table -> dict)
      2) st.secrets['GSERVICE_JSON'] (string or dict)
      3) env GSERVICE_JSON (string)
      4) local file gservice.json (dev fallback)
    Returns a dict suitable for Credentials.from_service_account_info(...)
    Raises RuntimeError if not found or invalid.
    """
    # 1) Streamlit table (preferred)
    st_sa = _st_secrets_get("gs_service")
    if isinstance(st_sa, dict):
        sa = dict(st_sa)  # copy
        if "private_key" in sa:
            sa["private_key"] = _normalize_private_key(sa["private_key"])
        return sa

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
            # strip possible surrounding triple quotes
            if s.startswith('"""') and s.endswith('"""'):
                s = s[3:-3].strip()
            try:
                sa = json.loads(s)
                if "private_key" in sa:
                    sa["private_key"] = _normalize_private_key(sa["private_key"])
                return sa
            except Exception:
                # try unicode_escape decode fallback
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
        "Service account credentials not found. Add st.secrets['gs_service'] or GSERVICE_JSON env or gservice.json file."
    )


def _get_gsheet_id() -> str:
    # try streamlit secrets first
    sid = _st_secrets_get("GSHEET_ID")
    if sid:
        return str(sid).strip()
    # common alternate keys in secrets
    sid = _st_secrets_get("gsheet_id") or _st_secrets_get("gs_sheet_id")
    if sid:
        return str(sid).strip()
    # env fallback
    sid = _env_get("GSHEET_ID") or _env_get("gsheet_id")
    if sid:
        return sid.strip()
    # local file fallback
    if os.path.exists("gsheet_id.txt"):
        with open("gsheet_id.txt", "r", encoding="utf8") as fh:
            data = fh.read().strip()
            if data:
                return data
    raise RuntimeError("GSHEET_ID not found in st.secrets, environment, or gsheet_id.txt")


def get_gspread_client() -> gspread.Client:
    """
    Returns an authorized gspread client using credentials from secrets/env/file.
    """
    sa_info = _load_service_account_info()
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client


def _open_sheet():
    client = get_gspread_client()
    sheet_id = _get_gsheet_id()
    sh = client.open_by_key(sheet_id)
    ws = sh.sheet1
    return ws


def sheet_to_df() -> pd.DataFrame:
    """
    Read all records from the sheet and return a pandas DataFrame with expected columns.
    """
    ws = _open_sheet()
    rows = ws.get_all_records()  # list[dict]
    expected = ["id", "timestamp", "rating", "review", "ai_response", "ai_summary", "ai_actions"]
    if not rows:
        return pd.DataFrame(columns=expected)
    df = pd.DataFrame(rows)
    # ensure expected columns are present
    for c in expected:
        if c not in df.columns:
            df[c] = ""
    return df[expected]


def append_submission(row_dict: Dict[str, Any]) -> bool:
    """
    Append a submission row to the sheet. Ensures header exists.
    row_dict keys: id, timestamp, rating, review, ai_response, ai_summary, ai_actions
    """
    ws = _open_sheet()
    header = ["id", "timestamp", "rating", "review", "ai_response", "ai_summary", "ai_actions"]
    try:
        existing = ws.row_values(1)
    except Exception:
        existing = []
    # if no header or mismatch, write header
    if not existing or existing[: len(header)] != header:
        try:
            # insert header at top (works even if sheet empty)
            ws.update("A1:G1", [header])
        except Exception:
            # fallback to insert_row for older gspread versions
            ws.insert_row(header, 1)
    row = [row_dict.get(k, "") for k in header]
    ws.append_row(row, value_input_option="USER_ENTERED")
    return True


def update_submission_by_id(sub_id: str, updates: Dict[str, Any]) -> bool:
    """
    Find a row where 'id' matches sub_id and update columns provided in updates dict.
    Returns True if updated, False if not found.
    """
    ws = _open_sheet()
    records = ws.get_all_records()
    if not records:
        return False
    header = ws.row_values(1)
    for idx, rec in enumerate(records, start=2):  # sheet rows start at 1, header is row 1
        if str(rec.get("id")) == str(sub_id):
            for key, val in updates.items():
                if key in header:
                    col_index = header.index(key) + 1
                    ws.update_cell(idx, col_index, val)
            return True
    return False
