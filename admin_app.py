import os
import json
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


def _get_from_env(name: str):
    v = os.environ.get(name)
    if v:
        return v
    return None


def _get_from_streamlit_secrets(name: str):
    """
    Returns the secret from streamlit.secrets if available.
    Note: st.secrets may not be available outside Streamlit runtime.
    """
    try:
        import streamlit as _st  # local import to avoid requiring streamlit for non-Streamlit contexts
        if name in _st.secrets:
            return _st.secrets[name]
    except Exception:
        # not running in Streamlit or st.secrets not available
        return None
    return None


def _get_secret_raw(name: str):
    """
    Try sources in order:
      1) OS env var
      2) Streamlit secrets (string or dict)
      3) Local fallback files (gservice.json or gsheet_id.txt)
    Returns None if not found.
    """
    # 1) OS env
    v = _get_from_env(name)
    if v:
        return v

    # 2) streamlit secrets
    v = _get_from_streamlit_secrets(name)
    if v:
        return v

    # 3) local files (development fallback)
    if name == "GSERVICE_JSON":
        maybe = os.path.join(os.getcwd(), "gservice.json")
        if os.path.exists(maybe):
            with open(maybe, "r", encoding="utf8") as fh:
                return fh.read()
    if name == "GSHEET_ID":
        maybe = os.path.join(os.getcwd(), "gsheet_id.txt")
        if os.path.exists(maybe):
            with open(maybe, "r", encoding="utf8") as fh:
                return fh.read().strip()
    return None


def _load_service_account_info():
    """
    Returns a dict suitable to pass to Credentials.from_service_account_info(...)
    Accepts:
      - GSERVICE_JSON as a JSON string (in env or st.secrets)
      - gs_service table/dict in st.secrets (Streamlit TOML table)
      - gservice.json file in project root (dev)
    """
    # First try Streamlit table form (st.secrets["gs_service"]) which will be a dict
    try:
        st_val = _get_from_streamlit_secrets("gs_service")
        if isinstance(st_val, dict):
            # ensure private_key has newline characters (Streamlit preserves newlines)
            return st_val
    except Exception:
        pass

    raw = _get_secret_raw("GSERVICE_JSON")
    if not raw:
        raise RuntimeError(
            "Service account JSON not found. Set GSERVICE_JSON in env, st.secrets (minified JSON) "
            "or provide a [gs_service] table in Streamlit secrets, or put gservice.json in project root."
        )

    # If it's already a dict (some hosts might return a dict), just return it
    if isinstance(raw, dict):
        return raw

    # If it's a string try to parse json
    if isinstance(raw, str):
        # Sometimes users paste triple-quoted JSON (with surrounding quotes); try to clean
        s = raw.strip()
        # If the string looks like TOML section (starts with '{') we parse as JSON
        try:
            return json.loads(s)
        except Exception:
            # Try to remove surrounding triple quotes if present
            cleaned = s.strip()
            if cleaned.startswith('"""') and cleaned.endswith('"""'):
                cleaned = cleaned[3:-3].strip()
            if cleaned.startswith("'\"\"'") and cleaned.endswith("'\"\"'"):
                cleaned = cleaned[4:-4].strip()
            try:
                return json.loads(cleaned)
            except Exception as e:
                # Last attempt: if newlines are literal inside, replace literal \n sequences with actual newlines
                # (this handles cases where private_key was pasted with escaped newlines or with real ones)
                try:
                    maybe = cleaned.encode('utf-8').decode('unicode_escape')
                    return json.loads(maybe)
                except Exception:
                    raise RuntimeError("Failed to parse GSERVICE_JSON. Ensure it is valid JSON.") from e

    raise RuntimeError("Failed to load service account info.")


def get_gspread_client_from_env():
    sa_info = _load_service_account_info()
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client


def _open_sheet():
    # allow GSHEET_ID from env or streamlit secrets
    sheet_id_raw = _get_secret_raw("GSHEET_ID")
    if not sheet_id_raw:
        # as additional attempt, try streamlit secrets table key "gs_service_sheet_id"
        try:
            import streamlit as st
            if "gs_sheet_id" in st.secrets:
                sheet_id_raw = st.secrets["gs_sheet_id"]
        except Exception:
            pass

    if not sheet_id_raw:
        raise RuntimeError("GSHEET_ID environment variable not set (or gsheet_id.txt missing).")
    SHEET_ID = sheet_id_raw.strip()
    client = get_gspread_client_from_env()
    sh = client.open_by_key(SHEET_ID)
    ws = sh.sheet1
    return ws


def sheet_to_df():
    ws = _open_sheet()
    rows = ws.get_all_records()
    if not rows:
        cols = ["id", "timestamp", "rating", "review", "ai_response", "ai_summary", "ai_actions"]
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    expected = ["id", "timestamp", "rating", "review", "ai_response", "ai_summary", "ai_actions"]
    for c in expected:
        if c not in df.columns:
            df[c] = ""
    return df[expected]


def append_submission(row_dict):
    ws = _open_sheet()
    header = ["id", "timestamp", "rating", "review", "ai_response", "ai_summary", "ai_actions"]
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
