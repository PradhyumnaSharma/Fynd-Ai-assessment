import os, uuid
from datetime import datetime
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from utils.gemini_helper import genai_generate_text
from utils.sheets_helper import sheet_to_df, append_submission
load_dotenv()

st.set_page_config(page_title="Fynd AI — User", layout="wide")
st.title("User Dashboard — Submit a Review")

with st.form("review_form"):
    rating = st.slider("Select rating (1 to 5)", 1, 5, 5)
    review = st.text_area("Write a short review", height=140)
    submitted = st.form_submit_button("Submit")

if submitted:
    if not review.strip():
        st.warning("Please write a short review before submitting.")
    else:
        with st.spinner("Generating AI outputs..."):
            prompt_reply = f"Write a short friendly reply (1-2 sentences) to this review: \"{review}\""
            prompt_summary = f"Summarize the review in one short sentence: \"{review}\""
            prompt_actions = f"Give up to 3 recommended actions (bullet points) a business owner should take based on: \"{review}\""

            ok_r, ai_response = genai_generate_text(prompt_reply)
            ok_s, ai_summary = genai_generate_text(prompt_summary)
            ok_a, ai_actions = genai_generate_text(prompt_actions)

            if not ok_r:
                ai_response = "Thanks for your feedback! We appreciate you taking the time to write us. (AI currently unavailable.)"
            if not ok_s:
                ai_summary = review.strip()[:200]
            if not ok_a:
                low = review.lower()
                suggestions = []
                if any(w in low for w in ["slow","wait","waiting","delay"]):
                    suggestions.append("- Investigate service speed and staffing.")
                if any(w in low for w in ["cold","undercooked","burnt","temperature"]):
                    suggestions.append("- Check food preparation & temperature controls.")
                if any(w in low for w in ["rude","unfriendly","hostile"]):
                    suggestions.append("- Provide staff training on customer service.")
                if not suggestions:
                    suggestions = ["- Thank the customer and ask for more details."]
                ai_actions = "\n".join(suggestions)

        row = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "rating": int(rating),
            "review": review,
            "ai_response": ai_response,
            "ai_summary": ai_summary,
            "ai_actions": ai_actions
        }

        try:
            append_submission(row)
        except Exception as e:
            st.error("Failed to save submission to Google Sheets: " + str(e))
            # fallback: keep local copy
            os.makedirs("data", exist_ok=True)
            local_file = "data/submissions_backup.csv"
            df_local = pd.DataFrame([row])
            if os.path.exists(local_file):
                df_local = pd.concat([pd.read_csv(local_file), df_local], ignore_index=True)
            df_local.to_csv(local_file, index=False)
            st.info("Saved to local backup: " + local_file)
            st.stop()

        st.success("Submitted — AI reply shown below.")
        st.write(ai_response)
        st.subheader("AI Summary")
        st.write(ai_summary)
        st.subheader("AI Recommended Actions")
        st.write(ai_actions)
