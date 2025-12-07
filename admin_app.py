import streamlit as st, json, traceback
from google.oauth2.service_account import Credentials
import gspread

# --- BEGIN DEBUG SNIPPET: paste at top of admin_app.py (temporary) ---
import os, json, traceback
try:
    import streamlit as st
except Exception:
    st = None

def pretty(o):
    try:
        return json.dumps(o, indent=2)
    except Exception:
        return str(o)

print("\n--- ADMIN DEBUG START ---\n")

# 1) Show if streamlit context exists
print("streamlit available:", bool(st))

# 2) Print env variables that matter
for k in ("GSHEET_ID","GSERVICE_JSON","GEMINI_API_KEY"):
    print(f"ENV {k}:", bool(os.environ.get(k)), "value head:", repr((os.environ.get(k) or "")[:120]))

# 3) If streamlit exists, print secrets keys / presence
if st:
    try:
        keys = list(st.secrets.keys())
    except Exception as e:
        keys = f"st.secrets read error: {e}"
    print("st.secrets keys:", keys)
    # show gs_service content summary
    if "gs_service" in getattr(st, "secrets", {}):
        svc = st.secrets["gs_service"]
        print("st.secrets['gs_service'] keys:", list(svc.keys()))
        pk = svc.get("private_key")
        print("private_key length:", len(pk) if pk else None)
        print("private_key contains real newline?:", ("\n" in pk) if pk else None)
    else:
        print("st.secrets['gs_service'] MISSING")

# 4) See if local gservice.json or .streamlit/secrets.toml exist
print("local gservice.json exists:", os.path.exists("gservice.json"))
print(".streamlit/secrets.toml exists:", os.path.exists(".streamlit/secrets.toml"))

# 5) Try to import and call loader from utils.sheets_helper and show exception if any
try:
    from utils.sheets_helper import _load_service_account_info, _get_gsheet_id
    try:
        info = _load_service_account_info()
        print("loader: found sa_info keys:", list(info.keys()))
    except Exception as e:
        print("loader error:", repr(e))
        print(traceback.format_exc())
    try:
        sid = _get_gsheet_id()
        print("loader: GSHEET_ID resolved ->", sid)
    except Exception as e:
        print("loader GSHEET_ID error:", repr(e))
        print(traceback.format_exc())
except Exception as e:
    print("Could not import utils.sheets_helper:", repr(e))
    print(traceback.format_exc())

print("\n--- ADMIN DEBUG END ---\n")
# --- END DEBUG SNIPPET ---

import pandas as pd
from dotenv import load_dotenv
from utils.gemini_helper import genai_generate_text
from utils.sheets_helper import sheet_to_df, update_submission_by_id
load_dotenv()

st.set_page_config(page_title="Fynd AI — Admin", layout="wide")
st.title("Admin Dashboard — Submissions")

try:
    df = sheet_to_df()
except Exception as e:
    st.error("Failed to read data from Google Sheets: " + str(e))
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




