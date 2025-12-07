import os, json,time
import streamlit as st

st.header("DEBUG: GSERVICE secret inspect")

if "gs_service" in st.secrets:
    svc = st.secrets["gs_service"]
    st.write("gs_service keys:", list(svc.keys()))
    pk = svc.get("private_key")
    if pk is None:
        st.error("private_key missing in gs_service")
    else:
        st.write("private_key length:", len(pk))
        st.write("private_key contains real newline? ->", "\n" in pk)
        st.write("private_key contains escaped backslash-n sequence? ->", "\\n" in pk)
        st.text("private_key repr head (first 200 chars):")
        st.code(repr(pk[:200]))
else:
    st.error("st.secrets['gs_service'] not present")


debug_secrets()
import streamlit as st
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


