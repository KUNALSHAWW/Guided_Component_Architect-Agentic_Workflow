"""
Guided Component Architect — Agentic Workflow
==============================================
An agentic pipeline that generates Angular + Tailwind CSS components,
validates them against a strict Design System (design.json), and
self-corrects through an automated feedback loop.

Author : Pythrust Engineering Assignment
Stack  : Python · Groq SDK · LLaMA 3.3-70B
"""

import os
import re
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

# ──────────────────────────────────────────────
# 1. CONFIGURATION & SETUP
# ──────────────────────────────────────────────

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("[ERROR] GROQ_API_KEY not found. Add it to a .env file.")
    sys.exit(1)

client = Groq(api_key=GROQ_API_KEY)

MODEL = "llama-3.3-70b-versatile"
MAX_RETRIES = 3
DESIGN_FILE = Path(__file__).parent / "design.json"


def load_design_tokens(filepath: Path = DESIGN_FILE) -> dict:
    """Load and parse the design system tokens from design.json."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("tokens", {})
    except FileNotFoundError:
        print(f"[ERROR] Design file not found at {filepath}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in design file: {e}")
        sys.exit(1)


# ──────────────────────────────────────────────
# 2. THE GENERATOR (Prompt Engineering)
# ──────────────────────────────────────────────

def build_system_prompt(design_tokens: dict) -> str:
    """
    Construct a strict system prompt that injects the design tokens
    and forces the LLM to output only raw Angular/Tailwind code.
    """
    tokens_str = json.dumps(design_tokens, indent=2)

    return f"""You are an expert Angular + Tailwind CSS component engineer.
You MUST follow these rules with ZERO exceptions:

DESIGN SYSTEM TOKENS (mandatory — every component must reference these):
{tokens_str}

OUTPUT RULES:
1. Output ONLY raw Angular component code. Include @Component decorator, template, and styles.
2. You MUST use inline styles or Tailwind utilities that include the EXACT hex values from the design tokens above.
   - The primary color {design_tokens.get('primary-color', '')} MUST appear in the output.
   - The secondary color {design_tokens.get('secondary-color', '')} MUST appear in the output.
   - The font family "{design_tokens.get('font', '')}" MUST appear in the output.
   - The border-radius value {design_tokens.get('border-radius', '')} MUST appear in the output.
3. NEVER wrap the code in markdown code fences (no ```html, ```typescript, or ```).
4. NEVER include conversational text, explanations, or commentary.
5. NEVER start with "Here is" or similar phrasing.
6. Output must start directly with import statements or the @Component decorator.
7. Use Tailwind CSS utility classes wherever possible, supplemented by inline [style] bindings for exact token values.
8. Ensure balanced HTML tags (<tag></tag>) and balanced curly brackets in TypeScript.

REMEMBER: Raw code ONLY. No markdown. No explanation. Just the Angular component."""


def call_llm(messages: list[dict]) -> str:
    """
    Call the Groq API with the given message history.
    Returns the raw text content from the assistant response.
    """
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=4096,
            top_p=0.9,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERROR] Groq API call failed: {e}")
        return ""


def generate_component(user_prompt: str, design_tokens: dict, chat_history: list[dict]) -> str:
    """
    Send the user prompt along with the system prompt and history to the LLM.
    Returns the raw generated code string.
    """
    system_prompt = build_system_prompt(design_tokens)

    # Build messages: system prompt first, then prior conversation, then new request
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(chat_history)
    messages.append({"role": "user", "content": user_prompt})

    code = call_llm(messages)

    # Strip accidental markdown fences the LLM might still emit
    code = strip_markdown_fences(code)

    return code


def strip_markdown_fences(code: str) -> str:
    """Remove markdown code fences if the LLM accidentally includes them."""
    # Remove opening fences like ```html, ```typescript, ```ts, ```
    code = re.sub(r"^```(?:html|typescript|ts|angular|css)?\s*\n?", "", code, flags=re.MULTILINE)
    # Remove closing fences
    code = re.sub(r"\n?```\s*$", "", code, flags=re.MULTILINE)
    return code.strip()


# ──────────────────────────────────────────────
# 3. THE VALIDATOR (Linter-Agent)
# ──────────────────────────────────────────────

def validate_code(code: str, design_tokens: dict) -> tuple[bool, str]:
    """
    Validate generated code against design tokens and basic syntax rules.

    Returns:
        (is_valid: bool, error_message: str)
    """
    errors: list[str] = []

    if not code or len(code.strip()) < 20:
        return False, "Generated code is empty or too short."

    # ── Token Presence Checks ──
    primary = design_tokens.get("primary-color", "")
    secondary = design_tokens.get("secondary-color", "")
    font = design_tokens.get("font", "")
    border_radius = design_tokens.get("border-radius", "")

    if primary and primary.lower() not in code.lower():
        errors.append(
            f"Missing primary color: '{primary}'. "
            f"You MUST include the exact hex value {primary} in an inline style or Tailwind arbitrary value like [color:{primary}]."
        )

    if secondary and secondary.lower() not in code.lower():
        errors.append(
            f"Missing secondary color: '{secondary}'. "
            f"You MUST include the exact hex value {secondary} in an inline style or Tailwind arbitrary value."
        )

    if font and font.lower() not in code.lower():
        errors.append(
            f"Missing font family: '{font}'. "
            f"You MUST include font-family: '{font}' in a style attribute or Tailwind class like font-['{font}']."
        )

    if border_radius and border_radius not in code:
        errors.append(
            f"Missing border-radius value: '{border_radius}'. "
            f"You MUST include border-radius: {border_radius} in an inline style or Tailwind arbitrary value like rounded-[{border_radius}]."
        )

    # ── Syntax Balance Checks ──
    # Check balanced curly brackets
    open_curly = code.count("{")
    close_curly = code.count("}")
    if open_curly != close_curly:
        errors.append(
            f"Unbalanced curly brackets: found {open_curly} opening '{{' and {close_curly} closing '}}'. "
            f"Ensure every '{{' has a matching '}}'."
        )

    # Check balanced angle brackets (HTML tags)
    open_angle = code.count("<")
    close_angle = code.count(">")
    if open_angle != close_angle:
        errors.append(
            f"Unbalanced angle brackets: found {open_angle} '<' and {close_angle} '>'. "
            f"Ensure all HTML tags are properly opened and closed."
        )

    # Check for residual markdown code fences
    if "```" in code:
        errors.append(
            "Output contains markdown code fences (```). "
            "Remove ALL markdown formatting and return only raw code."
        )

    # ── Result ──
    if errors:
        return False, " | ".join(errors)

    return True, ""


# ──────────────────────────────────────────────
# 4. THE SELF-CORRECTION LOOP
# ──────────────────────────────────────────────

def agentic_loop(user_prompt: str, design_tokens: dict, chat_history: list[dict]) -> tuple[str, list[dict]]:
    """
    Orchestrate the generate → validate → self-correct loop.

    Args:
        user_prompt: The user's component description.
        design_tokens: Parsed design system tokens.
        chat_history: Running conversation history for multi-turn editing.

    Returns:
        (final_code: str, updated_chat_history: list[dict])
    """
    print(f"\n{'─' * 60}")
    print(f"[AGENT] Generating component for: \"{user_prompt}\"")
    print(f"{'─' * 60}")

    attempt = 0
    current_prompt = user_prompt

    while attempt < MAX_RETRIES:
        attempt += 1
        print(f"\n  [Attempt {attempt}/{MAX_RETRIES}] Calling LLM...")

        code = generate_component(current_prompt, design_tokens, chat_history)

        if not code:
            print("  [WARN] LLM returned empty response. Retrying...")
            current_prompt = (
                f"Your previous response was empty. Please generate a valid Angular component for: "
                f"{user_prompt}. Return ONLY raw code, no markdown."
            )
            continue

        print(f"  [INFO] Received {len(code)} characters of code.")
        print(f"  [INFO] Validating against design system...")

        is_valid, error_message = validate_code(code, design_tokens)

        if is_valid:
            print("  [PASS] Validation successful!")
            # Update chat history with the successful exchange
            chat_history.append({"role": "user", "content": user_prompt})
            chat_history.append({"role": "assistant", "content": code})
            return code, chat_history

        print(f"  [FAIL] Validation errors: {error_message}")

        # Build the correction prompt and append to history for context
        correction_prompt = (
            f"The validation failed with these errors: {error_message}\n\n"
            f"Fix the code and return ONLY the raw fixed Angular component code. "
            f"No markdown fences, no explanations. "
            f"Make sure to include ALL required design tokens as exact values in the output."
        )

        # Temporarily extend history for the correction call
        chat_history.append({"role": "user", "content": user_prompt})
        chat_history.append({"role": "assistant", "content": code})
        current_prompt = correction_prompt

    # Exhausted retries
    print(f"\n  [ERROR] Failed after {MAX_RETRIES} attempts. Returning last generated code.")
    chat_history.append({"role": "user", "content": user_prompt})
    chat_history.append({"role": "assistant", "content": code})
    return code, chat_history


# ──────────────────────────────────────────────
# 5. EXPORT FEATURE
# ──────────────────────────────────────────────

def export_component(code: str) -> None:
    """Prompt the user to save the validated component to a file."""
    save = input("\n  [EXPORT] Save this component to a file? (y/n): ").strip().lower()
    if save != "y":
        print("  [SKIP] Component not saved.")
        return

    filename = input(
        "  [EXPORT] Enter filename (default: component.ts): "
    ).strip()

    if not filename:
        filename = "component.ts"

    # Ensure the file has an extension
    if "." not in filename:
        ext = input(
            "  [EXPORT] Choose extension — .ts / .html / .tsx (default: .ts): "
        ).strip()
        ext = ext if ext.startswith(".") else f".{ext}" if ext else ".ts"
        filename += ext

    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / filename

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"  [SAVED] Component saved to: {output_path}")
    except IOError as e:
        print(f"  [ERROR] Failed to save file: {e}")


# ──────────────────────────────────────────────
# 6. MAIN — Multi-Turn Interactive Loop
# ──────────────────────────────────────────────

def main():
    """Entry point: interactive multi-turn component generation."""
    print("=" * 60)
    print("  GUIDED COMPONENT ARCHITECT — Agentic Workflow")
    print("  Powered by Groq + LLaMA 3.3-70B")
    print("=" * 60)
    print()
    print("  Describe an Angular + Tailwind component and the agent")
    print("  will generate, validate, and self-correct it against")
    print("  your design system.")
    print()
    print("  Commands:")
    print("    'exit' or 'quit'  — End the session")
    print("    'reset'           — Clear conversation history")
    print("    'tokens'          — Display active design tokens")
    print()

    design_tokens = load_design_tokens()
    chat_history: list[dict] = []

    while True:
        try:
            user_input = input("\n[YOU] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n[AGENT] Session ended. Goodbye!")
            break

        if not user_input:
            continue

        # ── Special Commands ──
        if user_input.lower() in ("exit", "quit"):
            print("\n[AGENT] Session ended. Goodbye!")
            break

        if user_input.lower() == "reset":
            chat_history.clear()
            print("[AGENT] Conversation history cleared.")
            continue

        if user_input.lower() == "tokens":
            print("\n[DESIGN TOKENS]")
            print(json.dumps(design_tokens, indent=2))
            continue

        # ── Run the Agentic Loop ──
        code, chat_history = agentic_loop(user_input, design_tokens, chat_history)

        if code:
            print(f"\n{'─' * 60}")
            print("[GENERATED COMPONENT]")
            print(f"{'─' * 60}")
            print(code)
            print(f"{'─' * 60}")

            # Offer export
            export_component(code)
        else:
            print("\n[AGENT] Could not generate a valid component. Try rephrasing.")


if __name__ == "__main__":
    main()
