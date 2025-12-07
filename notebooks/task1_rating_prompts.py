import os,sys, time, json
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
import pandas as pd
from sklearn.metrics import accuracy_score
from dotenv import load_dotenv
from utils.gemini_helper import genai_generate_text

load_dotenv()

os.makedirs("data", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

df = pd.read_csv("data/yelp.csv")
cols = {c:c.lower() for c in df.columns}
df = df.rename(columns=cols)

if 'text' in df.columns:
    df = df.rename(columns={'text':'review'})
if 'review' not in df.columns:
    for c in df.columns:
        if 'review' in c:
            df = df.rename(columns={c:'review'})
            break
if 'stars' not in df.columns:
    for c in df.columns:
        if 'star' in c or 'rating' in c:
            df = df.rename(columns={c:'stars'})
            break
if 'review' not in df.columns or 'stars' not in df.columns:
    raise RuntimeError("Could not find 'review' and 'stars' columns in data/yelp.csv")

sample_n = min(200, len(df))
sample = df.sample(n=sample_n, random_state=42)[['review','stars']].reset_index(drop=True)
sample = sample.rename(columns={'stars':'true_stars'})
sample.to_csv("data/eval_sample.csv", index=False)

PROMPT_A = '''You are a concise assistant. Read the review and output EXACTLY a valid JSON object with keys:\n{{"predicted_stars": <integer 1-5>, "explanation":"<brief reason>"}}\nReturn only the JSON object and nothing else.\n\nReview:\n\"\"\"{review}\"\"\"'''

PROMPT_B = '''You are an assistant that maps user reviews to 1-5 star ratings.\nExamples:\nReview: "Food was cold and service was slow." -> 1\nReview: "Great food and friendly staff, would return." -> 4\nReview: "Okay for price, not special." -> 3\n\nNow read the review and output EXACTLY a JSON object: {{\"predicted_stars\": <1-5>, \"explanation\":\"<brief reason>\"}}. Nothing else.\n\nReview:\n\"\"\"{review}\"\"\"'''

PROMPT_C = '''First output one short line with sentiment polarity and strength like:\nSentiment: positive (strength: high)\nThen output EXACTLY a JSON object with keys {{\"predicted_stars\" (1-5), \"explanation\"}}. Do not output anything else.\n\nReview:\n\"\"\"{review}\"\"\"'''

results = {}
for name, prompt_template in [('A', PROMPT_A), ('B', PROMPT_B), ('C', PROMPT_C)]:
    outs = []
    for _, row in sample.iterrows():
        prompt = prompt_template.format(review=row['review'])
        ok, text = genai_generate_text(prompt, temperature=0.0)
        if not ok:
            text = text
        outs.append(text)
        time.sleep(0.12)
    sample[f'raw_{name}'] = outs
    preds = []
    valids = []
    for out in outs:
        try:
            s = out
            if not isinstance(s, str):
                preds.append(None); valids.append(False); continue
            start = s.find('{'); end = s.rfind('}')
            if start==-1 or end==-1:
                preds.append(None); valids.append(False); continue
            j = json.loads(s[start:end+1])
            ps = j.get('predicted_stars')
            if isinstance(ps, int) and 1<=ps<=5:
                preds.append(ps); valids.append(True)
            else:
                try:
                    ival = int(ps)
                    if 1<=ival<=5:
                        preds.append(ival); valids.append(True)
                    else:
                        preds.append(None); valids.append(False)
                except Exception:
                    preds.append(None); valids.append(False)
        except Exception:
            preds.append(None); valids.append(False)
    sample[f'pred_{name}'] = preds
    sample[f'valid_{name}'] = valids
    results[name] = sample[[f'pred_{name}', f'valid_{name}']]

summary = []
for name in ['A','B','C']:
    valid_mask = sample[f'valid_{name}']
    json_valid_rate = sum(valid_mask)/len(valid_mask)
    valid_rows = sample[valid_mask]
    acc = None
    if len(valid_rows)>0:
        acc = accuracy_score(valid_rows['true_stars'], valid_rows[f'pred_{name}'])
    summary.append({'Approach':name, 'Accuracy':acc, 'JSON_valid_rate':json_valid_rate})

pd.DataFrame(summary).to_csv('outputs/summary_table.csv', index=False)
sample.to_csv('outputs/eval_full.csv', index=False)
print('Done. outputs saved to outputs/')
