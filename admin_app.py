import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from utils.gemini_helper import genai_generate_text

load_dotenv()

DATA_FILE = "data/submissions.csv"
os.makedirs("data", exist_ok=True)
if not os.path.exists(DATA_FILE):
    pd.DataFrame(columns=["id","timestamp","rating","review","ai_response","ai_summary","ai_actions"]).to_csv(DATA_FILE, index=False)

st.set_page_config(page_title="Fynd AI — Admin", layout="wide")
st.title("Admin Dashboard — Submissions")

df = pd.read_csv(DATA_FILE)

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
                    if ok_s:
                        df.loc[df['id'] == sel_id, 'ai_summary'] = new_summary
                    if ok_a:
                        df.loc[df['id'] == sel_id, 'ai_actions'] = new_actions
                    df.to_csv(DATA_FILE, index=False)
                st.success("Updated AI outputs for selected entry.")
                st.experimental_rerun()
