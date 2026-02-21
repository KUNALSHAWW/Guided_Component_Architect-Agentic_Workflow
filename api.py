"""
Guided Component Architect — Web API (Vercel Serverless)
=========================================================
FastAPI wrapper around the agentic pipeline for web deployment.
"""

import os
import json
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from groq import Groq

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = "llama-3.3-70b-versatile"
MAX_RETRIES = 3
DESIGN_FILE = Path(__file__).parent / "design.json"

app = FastAPI(title="Guided Component Architect")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# DESIGN TOKENS
# ──────────────────────────────────────────────

def load_design_tokens() -> dict:
    try:
        with open(DESIGN_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("tokens", {})
    except Exception:
        return {
            "primary-color": "#6366f1",
            "secondary-color": "#ec4899",
            "border-radius": "8px",
            "font": "Inter",
        }


# ──────────────────────────────────────────────
# GENERATOR
# ──────────────────────────────────────────────

def build_system_prompt(tokens: dict) -> str:
    tokens_str = json.dumps(tokens, indent=2)
    return f"""You are an expert Angular + Tailwind CSS component engineer.
You MUST follow these rules with ZERO exceptions:

DESIGN SYSTEM TOKENS (mandatory — every component must reference these):
{tokens_str}

OUTPUT RULES:
1. Output ONLY raw Angular component code. Include @Component decorator, template, and styles.
2. You MUST use inline styles or Tailwind utilities that include the EXACT hex values from the design tokens above.
   - The primary color {tokens.get('primary-color', '')} MUST appear in the output.
   - The secondary color {tokens.get('secondary-color', '')} MUST appear in the output.
   - The font family "{tokens.get('font', '')}" MUST appear in the output.
   - The border-radius value {tokens.get('border-radius', '')} MUST appear in the output.
3. NEVER wrap the code in markdown code fences (no ```html, ```typescript, or ```).
4. NEVER include conversational text, explanations, or commentary.
5. NEVER start with "Here is" or similar phrasing.
6. Output must start directly with import statements or the @Component decorator.
7. Use Tailwind CSS utility classes wherever possible, supplemented by inline [style] bindings for exact token values.
8. Ensure balanced HTML tags and balanced curly brackets in TypeScript.

REMEMBER: Raw code ONLY. No markdown. No explanation. Just the Angular component."""


def strip_markdown_fences(code: str) -> str:
    code = re.sub(r"^```(?:html|typescript|ts|angular|css)?\s*\n?", "", code, flags=re.MULTILINE)
    code = re.sub(r"\n?```\s*$", "", code, flags=re.MULTILINE)
    return code.strip()


def call_llm(messages: list[dict]) -> str:
    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=4096,
            top_p=0.9,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"// ERROR: {e}"


# ──────────────────────────────────────────────
# VALIDATOR
# ──────────────────────────────────────────────

def validate_code(code: str, tokens: dict) -> tuple[bool, str]:
    errors = []

    if not code or len(code.strip()) < 20:
        return False, "Generated code is empty or too short."

    primary = tokens.get("primary-color", "")
    secondary = tokens.get("secondary-color", "")
    font = tokens.get("font", "")
    border_radius = tokens.get("border-radius", "")

    if primary and primary.lower() not in code.lower():
        errors.append(f"Missing primary color: '{primary}'.")
    if secondary and secondary.lower() not in code.lower():
        errors.append(f"Missing secondary color: '{secondary}'.")
    if font and font.lower() not in code.lower():
        errors.append(f"Missing font family: '{font}'.")
    if border_radius and border_radius not in code:
        errors.append(f"Missing border-radius: '{border_radius}'.")

    open_curly = code.count("{")
    close_curly = code.count("}")
    if open_curly != close_curly:
        errors.append(f"Unbalanced curly brackets: {open_curly} '{{' vs {close_curly} '}}'.")

    open_angle = code.count("<")
    close_angle = code.count(">")
    if open_angle != close_angle:
        errors.append(f"Unbalanced angle brackets: {open_angle} '<' vs {close_angle} '>'.")

    if "```" in code:
        errors.append("Output contains markdown code fences.")

    return (True, "") if not errors else (False, " | ".join(errors))


# ──────────────────────────────────────────────
# AGENTIC LOOP
# ──────────────────────────────────────────────

def run_agentic_loop(user_prompt: str, chat_history: list[dict]) -> dict:
    """Run generator → validator → self-correction and return structured result."""
    tokens = load_design_tokens()
    system_prompt = build_system_prompt(tokens)
    logs = []

    current_prompt = user_prompt
    code = ""

    for attempt in range(1, MAX_RETRIES + 1):
        logs.append({"type": "info", "text": f"[Attempt {attempt}/{MAX_RETRIES}] Calling LLM..."})

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(chat_history)
        messages.append({"role": "user", "content": current_prompt})

        code = strip_markdown_fences(call_llm(messages))

        if not code or code.startswith("// ERROR"):
            logs.append({"type": "error", "text": f"LLM returned error or empty: {code}"})
            current_prompt = f"Your previous response was empty. Generate a valid Angular component for: {user_prompt}. Raw code only."
            continue

        logs.append({"type": "info", "text": f"Received {len(code)} characters of code."})

        is_valid, error_msg = validate_code(code, tokens)

        if is_valid:
            logs.append({"type": "success", "text": "Validation successful!"})
            chat_history.append({"role": "user", "content": user_prompt})
            chat_history.append({"role": "assistant", "content": code})
            return {
                "code": code,
                "valid": True,
                "attempts": attempt,
                "logs": logs,
                "history": chat_history,
            }

        logs.append({"type": "fail", "text": f"Validation failed: {error_msg}"})

        chat_history.append({"role": "user", "content": user_prompt})
        chat_history.append({"role": "assistant", "content": code})
        current_prompt = (
            f"The validation failed with these errors: {error_msg}\n\n"
            f"Fix the code and return ONLY the raw fixed Angular component code."
        )

    # Exhausted retries
    logs.append({"type": "error", "text": f"Failed after {MAX_RETRIES} attempts."})
    return {
        "code": code,
        "valid": False,
        "attempts": MAX_RETRIES,
        "logs": logs,
        "history": chat_history,
    }


# ──────────────────────────────────────────────
# API ROUTES
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the single-page frontend."""
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.post("/api/generate")
async def generate(request: Request):
    """Main generation endpoint."""
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    history = body.get("history", [])

    if not prompt:
        return JSONResponse({"error": "Prompt is required."}, status_code=400)

    if not GROQ_API_KEY:
        return JSONResponse({"error": "GROQ_API_KEY not configured on server."}, status_code=500)

    result = run_agentic_loop(prompt, history)
    return JSONResponse(result)


@app.get("/api/tokens")
async def get_tokens():
    """Return the active design tokens."""
    return JSONResponse(load_design_tokens())


@app.get("/api/health")
async def health():
    return {"status": "ok", "model": MODEL}
