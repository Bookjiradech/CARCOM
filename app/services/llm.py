# app/services/llm.py
import os, json, re
import google.generativeai as genai

def pick_best_car(params: dict, cars: list[dict]):
    """
    params: from SearchSession.params_json (dict)
    cars: list of cars (dict) to let the LLM choose from
    return: (best_index: int|None, reason: str|None, raw_text: str)
    """
    api = os.getenv("GEMINI_API_KEY")
    if not api:
        return None, None, "NO_API_KEY"

    genai.configure(api_key=api)
    model = genai.GenerativeModel("gemini-1.5-flash")

    # Build a brief list for readability + 1-based 'index'
    brief = []
    for i, c in enumerate(cars, start=1):
        brief.append({
            "index": i,
            "title": c.get("title"),
            "brand": c.get("brand"),
            "model": c.get("model"),
            "year": c.get("year"),
            "mileage_km": c.get("mileage_km"),
            "price_thb": c.get("price_thb"),
            "fuel_type": c.get("fuel_type"),
            "transmission": c.get("transmission"),
        })

    system = (
        "You are a used-car recommendation assistant. Choose exactly 1 car that best fits the user, "
        "considering budget and user context."
    )

    # Ask for JSON to reduce parsing issues
    prompt = {
        "params": params,
        "cars": brief,
        "instruction": (
            "Output JSON only with the shape:\n"
            '{ "best_index": <integer 1..N>, "reason": ">= 100 chars (English)" }'
        )
    }

    resp = model.generate_content(
        contents=[system, "Data:", json.dumps(prompt, ensure_ascii=False)]
    )

    text = resp.text or ""
    # Extract JSON
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None, None, text

    try:
        data = json.loads(m.group(0))
        best = int(data.get("best_index")) if "best_index" in data else None
        reason = data.get("reason")
        # Clamp range
        if best is not None and (best < 1 or best > len(cars)):
            best = None
        return best, reason, text
    except Exception:
        return None, None, text
