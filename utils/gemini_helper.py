import os, logging, traceback, json, time
from tenacity import retry, wait_exponential, stop_after_attempt
from google import genai

os.makedirs("logs", exist_ok=True)
logging.basicConfig(filename="logs/genai_errors.log",
                    level=logging.DEBUG,
                    format="%(asctime)s %(levelname)s %(message)s")

MODEL = "gemini-2.5-flash-lite"

def get_client():
    try:
        client = genai.Client()
        return client
    except Exception as e:
        logging.error("Failed to create genai.Client()", exc_info=True)
        raise

CLIENT = get_client()

def _extract_text_from_response(resp):
    try:
        if isinstance(resp, str):
            return True, resp, "str"
        if hasattr(resp, "text"):
            try:
                return True, resp.text, "has .text"
            except Exception:
                pass
        if hasattr(resp, "candidates"):
            try:
                cand0 = resp.candidates[0]
                if hasattr(cand0, "content") and hasattr(cand0.content, "parts"):
                    parts = cand0.content.parts
                    text = "".join([getattr(p, "text", str(p)) for p in parts])
                    return True, text, "candidates->content.parts"
                if hasattr(cand0, "text"):
                    return True, cand0.text, "candidates->text"
            except Exception:
                pass
        try:
            if isinstance(resp, dict):
                if "candidates" in resp and len(resp["candidates"])>0:
                    c0 = resp["candidates"][0]
                    if isinstance(c0, dict) and "content" in c0:
                        cont = c0["content"]
                        if isinstance(cont, dict) and "parts" in cont:
                            parts = cont["parts"]
                            txt = "".join([p.get("text", "") if isinstance(p, dict) else str(p) for p in parts])
                            return True, txt, "dict candidates->content.parts"
                if "text" in resp:
                    return True, resp["text"], "dict->text"
                if "output" in resp:
                    return True, str(resp["output"]), "dict->output"
        except Exception:
            pass
        if hasattr(resp, "to_dict"):
            try:
                d = resp.to_dict()
                return _extract_text_from_response(d)
            except Exception:
                pass
        if hasattr(resp, "to_json"):
            try:
                j = json.loads(resp.to_json())
                return _extract_text_from_response(j)
            except Exception:
                pass
        if hasattr(resp, "result") and callable(getattr(resp, "result")):
            try:
                resolved = resp.result()
                return _extract_text_from_response(resolved)
            except Exception:
                pass
        return False, None, f"unrecognized-response-type: {type(resp)}; repr: {repr(resp)[:400]}"
    except Exception as exc:
        return False, None, f"_extract_text_exception: {repr(exc)}"

@retry(wait=wait_exponential(multiplier=0.5, min=0.5, max=4), stop=stop_after_attempt(3))
def genai_generate_text(prompt, temperature=0.0, max_output_tokens=250):
    try:
        resp = CLIENT.models.generate_content(model=MODEL, contents=prompt)
        ok, text, debug = _extract_text_from_response(resp)
        if ok and text:
            return True, text
        else:
            logging.error("genai returned non-text response. debug=%s repr=%s", debug, repr(resp)[:800])
            if hasattr(CLIENT, "generate"):
                try:
                    alt = CLIENT.generate(model=MODEL, prompt=prompt)
                    ok2, text2, dbg2 = _extract_text_from_response(alt)
                    if ok2 and text2:
                        return True, text2
                except Exception:
                    logging.exception("Alternative client.generate failed.")
            if hasattr(CLIENT, "models") and hasattr(CLIENT.models, "generate") :
                try:
                    alt2 = CLIENT.models.generate(model=MODEL, prompt=prompt)
                    ok3, text3, dbg3 = _extract_text_from_response(alt2)
                    if ok3 and text3:
                        return True, text3
                except Exception:
                    logging.exception("Alternative CLIENT.models.generate failed.")
            return False, f"ERROR: Unexpected response shape from Gemini SDK. debug={debug}"
    except Exception as exc:
        logging.error("Gemini generate exception", exc_info=True)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        with open("logs/last_genai_error.txt", "w", encoding="utf8") as fh:
            fh.write("TRACEBACK:\n")
            fh.write(tb)
        return False, f"ERROR: Gemini call failed: {repr(exc)}. See logs/last_genai_error.txt"
