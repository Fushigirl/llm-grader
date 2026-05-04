# coding: utf-8
"""LLM backend clients: UI (Playwright), Ollama, Claude API."""

import re
import requests
from playwright.sync_api import sync_playwright

OLLAMA_URL = "http://localhost:11434/api/chat"

_NOISE_PATTERNS = [
    r"^Qwen",
    r"^Reading$",
    r"^Generation$",
    r"^Processing\s+\d+%.*",       # "Processing 94% (ETA: 1s)" など（行全体）
    r"^\d+\s+tokens$",
    r"^\d+(\.\d+)?s$",
    r"^\d+(\.\d+)?\s+t/s$",
    r"^\d+(\.\d+)?\s+tokens/s$",  # "1617.35 tokens/s"
    r"^\d+\.\d+$",                # "3.6" などの数値のみ行
    r"^\d+B-A\d+B$",              # "35B-A3B" などのモデル名断片
]


def _clean_response(body_lines: list) -> str:
    """Join paragraph lines, protect '考察' text from noise removal, normalise whitespace."""
    joined = "\n".join(line for line in body_lines if line is not None)

    reflection_idx = joined.find("考察")
    if reflection_idx >= 0:
        before = joined[:reflection_idx]
        after  = joined[reflection_idx:]
        for pat in _NOISE_PATTERNS:
            before = re.sub(pat, "", before, flags=re.MULTILINE)
        # 考察より前の残留ノイズ行（空行・記号のみ等）を除去
        before = "\n".join(
            line for line in before.splitlines()
            if line.strip() and not re.match(r"^[\s\(\):\d\.%,/s]+$", line.strip())
        )
        joined = before + after
    else:
        for pat in _NOISE_PATTERNS:
            joined = re.sub(pat, "", joined, flags=re.MULTILINE)

    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return "\n".join(line.rstrip() for line in joined.splitlines()).strip()


def _get_body_lines(assistant_group) -> list:
    lines = [p for p in assistant_group.locator("p").all_inner_texts()]
    if not any(line.strip() for line in lines):
        lines = [assistant_group.inner_text()]
    return lines


def _wait_stable(page, assistant_group, polls: int = 20, interval_ms: int = 800,
                 required: int = 4) -> None:
    """Poll until inner_text length is stable for `required` consecutive reads."""
    stable_count, prev_len = 0, -1
    for _ in range(polls):
        txt = assistant_group.inner_text().strip()
        stable_count = stable_count + 1 if len(txt) == prev_len else 0
        prev_len = len(txt)
        if stable_count >= required:
            return
        page.wait_for_timeout(interval_ms)


def _looks_truncated(text: str) -> bool:
    """Return True if the response appears to have been cut off mid-sentence."""
    stripped = text.strip()
    if not stripped or "考察記述なし" in stripped:
        return False
    last_line = next(
        (line.strip() for line in reversed(stripped.splitlines()) if line.strip()), ""
    )
    return bool(last_line) and not re.search(r"[。．.!?！？】」』]$", last_line)


def extract_reflection_only(text: str) -> str:
    """Return only the reflection portion of the LLM response.

    Called by grade.py on phase-1 output only — never on phase-2 evaluation text.
    """
    if not isinstance(text, str):
        return ""

    idx = text.find("考察")
    if idx >= 0:
        # 直前が「【」なら括弧ごと残す
        start = idx - 1 if idx > 0 and text[idx - 1] == "【" else idx
        return text[start:].strip()

    raw_lines = text.splitlines()
    for i, line in enumerate(raw_lines):
        if line and "考察" in line:
            return "\n".join(l.rstrip() for l in raw_lines[i:]).strip()

    sections, current_title, current_body = [], None, []

    def _flush():
        if current_title and current_body:
            sections.append(current_title + "\n" + "\n".join(current_body).strip())

    for raw_line in [l.rstrip() for l in raw_lines]:
        line = raw_line.strip()
        if not line:
            if current_title and current_body:
                current_body.append("")
            continue
        if re.match(r"^【.*考察.*】$", line):
            _flush()
            current_title, current_body = line, []
        elif current_title is not None:
            current_body.append(raw_line)

    _flush()
    if sections:
        return "\n\n".join(s.strip() for s in sections if s.strip()).strip()

    return text.strip()


def call_ollama(prompt: str, model: str, max_tokens: int = 1200) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_predict": max_tokens},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=180)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def call_claude(prompt: str, model: str, max_tokens: int = 1200) -> str:
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def call_llm_ui(prompt: str, model: str, url: str,
                username: str, password: str) -> str:
    """Drive the web UI via Playwright to submit a prompt and return the response."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            http_credentials={"username": username, "password": password}
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=120000)

        textbox = page.get_by_role("textbox", name="Type a message...")
        textbox.wait_for(state="visible", timeout=60000)
        textbox.scroll_into_view_if_needed()
        textbox.click(force=True)
        textbox.press("Control+A")
        textbox.press("Backspace")
        textbox.fill(prompt)

        model_button = page.get_by_role("button", name=model)
        if model_button.count() > 0:
            model_button.first.click()

        send_button = page.get_by_role("button", name="Send")
        if not send_button.is_enabled():
            textbox.click(force=True)
            textbox.press("Control+A")
            page.keyboard.type(prompt)
        if not send_button.is_enabled():
            raise RuntimeError("Send button did not become enabled after input.")
        send_button.click()

        page.wait_for_function(
            """() => {
                const buttons = Array.from(document.querySelectorAll('button'));
                return !buttons.some(b => (b.textContent || '').trim() === 'Stop');
            }""",
            timeout=180000,
        )

        assistant_group = (
            page.get_by_role("group", name="Assistant message with actions").last
        )
        page.wait_for_function(
            "(group) => (group.innerText || '').trim().length > 0",
            arg=assistant_group.element_handle(),
            timeout=120000,
        )
        _wait_stable(page, assistant_group)

        cleaned = _clean_response(_get_body_lines(assistant_group))

        if _looks_truncated(cleaned):
            continuation_prompt = (
                "前の返答は途中で終わっているようです。"
                "直前までと重複しないように、切れた箇所の続きだけを同じ形式で最後まで返してください。"
                "考察以外は不要です。"
            )
            textbox.click(force=True)
            textbox.press("Control+A")
            textbox.press("Backspace")
            textbox.fill(continuation_prompt)
            send_button.click()

            page.wait_for_function(
                """() => {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    return !buttons.some(b => (b.textContent || '').trim() === 'Stop');
                }""",
                timeout=180000,
            )
            assistant_group = (
                page.get_by_role("group", name="Assistant message with actions").last
            )
            page.wait_for_function(
                "(group) => (group.innerText || '').trim().length > 0",
                arg=assistant_group.element_handle(),
                timeout=120000,
            )
            _wait_stable(page, assistant_group)

            continuation = _clean_response(_get_body_lines(assistant_group))
            if continuation and continuation != cleaned and continuation != "考察記述なし":
                cleaned = (cleaned.rstrip() + "\n" + continuation.lstrip()).strip()

        context.close()
        browser.close()
        return cleaned


def call_llm(
    prompt: str,
    backend: str,
    model: str,
    ui_url: str = "",
    ui_user: str = "",
    ui_pass: str = "",
    max_tokens: int = 1200,
) -> str:
    if backend == "ollama":
        return call_ollama(prompt, model, max_tokens)
    elif backend == "claude":
        return call_claude(prompt, model, max_tokens)
    else:
        return call_llm_ui(prompt, model, ui_url, ui_user, ui_pass)
