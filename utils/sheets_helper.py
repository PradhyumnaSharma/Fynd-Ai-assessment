# utils/sheets_helper.py  (PATCHED)
import os
import json
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def _get_secret(name):
    """
    Return secret value from (in order of preference):
      1) OS environment variable
      2) streamlit.secrets (if running under Streamlit Cloud)
      3) local fallback files (gsheet_id.txt or gservice.json)
    Returns None if not found.
    """
    # 1) OS env
    v = os.environ.get(name)
    if v:
        return v

    # 2) Streamlit secrets
    try:
        import streamlit as _st  # local import to avoid requiring streamlit in non-Streamlit contexts
        # st.secrets behaves like a mapping
        if name in _st.secrets:
            return _st.secrets[name]
    except Exception:
        pass

    # 3) local files (use only for local dev)
    if name == "GSHEET_ID":
        maybe = os.path.join(os.getcwd(), "gsheet_id.txt")
        if os.path.exists(maybe):
            with open(maybe, "r", encoding="utf8") as fh:
                return fh.read().strip()
    if name == "GSERVICE_JSON":
        maybe = os.path.join(os.getcwd(), "gservice.json")
        if os.path.exists(maybe):
            with open(maybe, "r", encoding="utf8") as fh:
                return fh.read()
    return None

def _load_service_account_info():
    sa_json_raw = _get_secret("GSERVICE_JSON")
    if not sa_json_raw:
        raise RuntimeError("Service account JSON not found. Set GSERVICE_JSON in env, streamlit secrets, or put gservice.json in project root.")
    # sa_json_raw may already be a JSON string (with triple quotes) — load it safely
    if isinstance(sa_json_raw, dict):
        return sa_json_raw
    try:
        return json.loads(sa_json_raw)
    except Exception as e:
        # Sometimes the secret includes extra newlines or quotes; try simple cleanup
        try:
            cleaned = sa_json_raw.strip().strip('"""').strip()
            return json.loads(cleaned)
        except Exception:
            raise RuntimeError("Failed to parse GSERVICE_JSON. Ensure it is valid JSON.") from e

def get_gspread_client_from_env():
    sa_info = _load_service_account_info()
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client

def _open_sheet():
    SHEET_ID = _get_secret("GSHEET_ID")
    if not SHEET_ID:
        raise RuntimeError("GSHEET_ID environment variable not set (or gsheet_id.txt missing).")
    client = get_gspread_client_from_env()
    sh = client.open_by_key(SHEET_ID)
    ws = sh.sheet1
    return ws

def sheet_to_df():
    ws = _open_sheet()
    rows = ws.get_all_records()  # returns list of dicts
    if not rows:
        cols = ["id","timestamp","rating","review","ai_response","ai_summary","ai_actions"]
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    expected = ["id","timestamp","rating","review","ai_response","ai_summary","ai_actions"]
    for c in expected:
        if c not in df.columns:
            df[c] = ""
    return df[expected]

def append_submission(row_dict):
    ws = _open_sheet()
    header = ["id","timestamp","rating","review","ai_response","ai_summary","ai_actions"]
    existing = ws.row_values(1)
    if not existing or existing[:len(header)] != header:
        ws.insert_row(header, 1)
    row = [row_dict.get(k, "") for k in header]
    ws.append_row(row, value_input_option="USER_ENTERED")
    return True

def update_submission_by_id(sub_id, updates: dict):
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
