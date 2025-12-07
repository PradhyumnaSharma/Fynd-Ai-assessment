import time
import os
import json
import traceback

import streamlit as st
import pandas as pd
from dotenv import load_dotenv

# --- debug / diagnostics (visible on the Streamlit page) ---
st.set_page_config(page_title="Fynd AI — Admin", layout="wide")
st.title("Admin Dashboard — Submissions (Debug Mode)")

st.markdown("### Debug: environment & secrets")
col1, col2 = st.columns(2)

with col1:
    st.write("**Environment variables (presence & head)**")
    for k in ("GSHEET_ID", "GSERVICE_JSON", "GEMINI_API_KEY"):
        v = os.environ.get(k, "")
        st.write(f"- {k}: present={bool(v)} head={repr(v[:120])}")

with col2:
    st.write("**Streamlit secrets keys**")
    try:
        keys = list(st.secrets.keys())
    except Exception as e:
        keys = f"st.secrets read error: {e}"
    st.write(keys)

st.write("**gs_service summary (if present)**")
if "gs_service" in getattr(st, "secrets", {}):
    svc = st.secrets["gs_service"]
    try:
        st.write("keys:", list(svc.keys()))
        pk = svc.get("private_key")
        st.write("private_key length:", len(pk) if pk else None)
        st.write("private_key contains real newline?:", ("\n" in pk) if pk else None)
    except Exception as e:
        st.write("error inspecting gs_service:", e)
else:
    st.write("st.secrets['gs_service'] MISSING")

st.write("**Local files**")
st.write("gservice.json exists:", os.path.exists("gservice.json"))
st.write(".streamlit/secrets.toml exists:", os.path.exists(".streamlit/secrets.toml"))

# Try to run loader functions from utils.sheets_helper and show results
from utils import sheets_helper as sheets_helper_mod  # import module to call internals
try:
    sa_info = sheets_helper_mod._load_service_account_info()
    st.success("Loader: loaded service account info keys: " + ", ".join(list(sa_info.keys())))
except Exception as e:
    st.error("Loader: failed to load service account info: " + str(e))
    st.text(traceback.format_exc())

try:
    sid = sheets_helper_mod._get_gsheet_id()
    st.success("Loader: GSHEET_ID resolved -> " + str(sid))
except Exception as e:
    st.error("Loader: failed to resolve GSHEET_ID: " + str(e))
    st.text(traceback.format_exc())

st.markdown("---")

# --- end debug / diagnostics ---

# Application imports that rely on sheets/gemini
from utils.gemini_helper import genai_generate_text
from utils.sheets_helper import sheet_to_df, update_submission_by_id

load_dotenv()  # keep for local dev convenience

st.title("Admin Dashboard — Submissions")

# Load submissions with graceful fallback
try:
    df = sheet_to_df()
    st.success(f"Loaded submissions from Google Sheets (rows={len(df)})")
except Exception as e:
    st.error("Failed to read data from Google Sheets: " + str(e))
    st.text(traceback.format_exc())
    # fallback to local backup CSV if available
    backup_path = "data/submissions_backup.csv"
    if os.path.exists(backup_path):
        try:
            df = pd.read_csv(backup_path)
            st.info(f"Loaded submissions from local backup ({backup_path}). Rows: {len(df)}")
        except Exception:
            df = pd.DataFrame(columns=["id","timestamp","rating","review","ai_response","ai_summary","ai_actions"])
    else:
        df = pd.DataFrame(columns=["id","timestamp","rating","review","ai_response","ai_summary","ai_actions"])

st.markdown(f"**Total submissions:** {len(df)} — **Avg rating:** {df['rating'].mean() if len(df)>0 else 'N/A'}")

if len(df) == 0:
    st.info("No submissions yet. Public users can submit reviews via the User Dashboard.")
else:
    view = st.radio("View options", ["Table", "Analytics", "Detail / Re-run AI"], index=0)

    if view == "Table":
        st.dataframe(df.sort_values("timestamp", ascending=False).reset_index(drop=True))

    elif view == "Analytics":
        st.subheader("Rating distribution")
        st.bar_chart(df['rating'].value_counts().sort_index())
        st.subheader("Latest summaries")
        st.table(df.sort_values("timestamp", ascending=False)[["timestamp","rating","ai_summary"]].head(10))

    else:
        st.subheader("Re-run AI for an entry")
        ids = df['id'].tolist()
        sel_id = st.selectbox("Select submission id", ids)
        if sel_id:
            sel_row = df[df['id'] == sel_id].iloc[0]
            st.markdown("**Review:**")
            st.write(sel_row['review'])
            st.markdown("**Current AI Summary:**")
            st.write(sel_row.get('ai_summary', ''))
            st.markdown("**Current AI Actions:**")
            st.write(sel_row.get('ai_actions', ''))

            if st.button("Re-run summary & actions"):
                with st.spinner("Re-running AI..."):
                    ok_s, new_summary = genai_generate_text(f"Summarize this review in one short sentence: \"{sel_row['review']}\"")
                    ok_a, new_actions = genai_generate_text(f"Give up to 3 recommended actions (bullet points) for this review: \"{sel_row['review']}\"")
                    updates = {}
                    if ok_s:
                        updates["ai_summary"] = new_summary
                    if ok_a:
                        updates["ai_actions"] = new_actions
                    if updates:
                        ok_upd = update_submission_by_id(sel_id, updates)
                        if not ok_upd:
                            st.error("Failed to update Google Sheet entry for selected ID.")
                        else:
                            st.success("Updated AI outputs for selected entry.")
                    else:
                        st.warning("LLM calls failed; nothing to update.")
                try:
                    st.experimental_set_query_params(_updated=str(int(time.time())))
                except Exception:
                    st.info("Please refresh the page to see updates.")
