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
    r"^\d+\s+tokens$",
    r"^\d+(\.\d+)?s$",
    r"^\d+(\.\d+)?\s+t/s$",
]


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
        textbox.click()
        textbox.press("Control+A")
        textbox.press("Backspace")
        textbox.fill(prompt)

        model_button = page.get_by_role("button", name=model)
        if model_button.count() > 0:
            model_button.first.click()

        send_button = page.get_by_role("button", name="Send")
        if not send_button.is_enabled():
            textbox.click()
            textbox.press("Control+A")
            page.keyboard.type(prompt)
        if not send_button.is_enabled():
            raise RuntimeError("Send button did not become enabled after input.")
        send_button.click()

        # Wait for generation to finish (Stop button disappears)
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

        # Poll until text length stabilises (streaming may still be writing)
        stable_count, prev_len = 0, -1
        for _ in range(8):
            txt = assistant_group.inner_text().strip()
            stable_count = stable_count + 1 if len(txt) == prev_len else 0
            prev_len = len(txt)
            if stable_count >= 2:
                break
            page.wait_for_timeout(300)

        body_lines = [
            p.strip()
            for p in assistant_group.locator("p").all_inner_texts()
            if p.strip()
        ]
        if not body_lines:
            body_lines = [assistant_group.inner_text().strip()]

        cleaned = [
            line for line in body_lines
            if not any(re.match(pat, line) for pat in _NOISE_PATTERNS)
        ]

        context.close()
        browser.close()
        return "\n".join(cleaned).strip()


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
