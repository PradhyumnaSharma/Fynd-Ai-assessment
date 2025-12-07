import streamlit as st, json, traceback
from google.oauth2.service_account import Credentials
import gspread

st.header("DEBUG: gspread/GSheets connectivity test")

try:
    # 1) get sa info
    if "gs_service" in st.secrets:
        sa_info = dict(st.secrets["gs_service"])
    elif "GSERVICE_JSON" in st.secrets:
        raw = st.secrets["GSERVICE_JSON"]
        sa_info = json.loads(raw) if isinstance(raw, str) else dict(raw)
    else:
        raise RuntimeError("No gs_service or GSERVICE_JSON in st.secrets")

    st.write("Service account keys present:", list(sa_info.keys()))
    st.write("service_account client_email:", sa_info.get("client_email"))

    # normalize private_key if needed
    if "private_key" in sa_info and isinstance(sa_info["private_key"], str):
        if "\\n" in sa_info["private_key"] and "\n" not in sa_info["private_key"]:
            sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")

    # 2) create credentials
    creds = Credentials.from_service_account_info(sa_info, scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ])
    st.success("Credentials created OK")

    # 3) authorize gspread
    client = gspread.authorize(creds)
    st.success("gspread authorized OK")

    # 4) open sheet
    sheet_id = st.secrets.get("GSHEET_ID") or st.secrets.get("gsheet_id")
    st.write("Using SHEET_ID:", sheet_id)
    if not sheet_id:
        st.error("GSHEET_ID missing in secrets!")
    else:
        sh = client.open_by_key(sheet_id)
        st.success("Spreadsheet opened OK: " + str(sh.title))
        ws = sh.sheet1
        rows = ws.get_all_records()
        st.write("Rows read:", len(rows))
except Exception as e:
    st.error("Error: " + str(e))
    st.text(traceback.format_exc())

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



