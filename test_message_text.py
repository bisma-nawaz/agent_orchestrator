"""
Unit tests for orchestrator.extract_message_text.

Regression guard for the bug where ``str(msg.content)`` leaked block reprs
(e.g. ``[TextBlock(text='...'), ThinkingBlock(...)]``) — and the model's
private reasoning — into agent output and final reports.

These use lightweight stub blocks (duck-typed on ``.text``) so they run
without an API key. The helper only depends on the ``.content`` attribute
and each block's ``.text``, exactly like the real SDK content blocks.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from orchestrator.orchestrator import extract_message_text


def _text_block(text):
    return SimpleNamespace(text=text)


def _thinking_block(thinking):
    # Mirrors SDK ThinkingBlock: has .thinking, no .text
    return SimpleNamespace(thinking=thinking, signature="sig")


def _tool_use_block(name):
    # Mirrors SDK ToolUseBlock: has .id/.name/.input, no .text
    return SimpleNamespace(id="t1", name=name, input={})


def test_extracts_only_text_blocks():
    msg = SimpleNamespace(
        content=[_text_block("First finding."), _text_block("Second finding.")]
    )
    assert extract_message_text(msg) == "First finding.\nSecond finding."


def test_drops_thinking_and_tool_blocks():
    msg = SimpleNamespace(
        content=[
            _thinking_block("secret private reasoning"),
            _text_block("Public answer."),
            _tool_use_block("WebSearch"),
        ]
    )
    out = extract_message_text(msg)
    assert out == "Public answer."
    # The model's private reasoning must never leak into output.
    assert "secret private reasoning" not in out
    # No block repr should survive.
    assert "SimpleNamespace" not in out and "thinking=" not in out


def test_plain_string_content_passthrough():
    assert extract_message_text(SimpleNamespace(content="raw text")) == "raw text"


def test_result_message_without_content_yields_empty():
    # ResultMessage has no .content attribute (text lives in .result);
    # the streaming loop accumulates AssistantMessage text, so this returns "".
    assert extract_message_text(SimpleNamespace(result="final", is_error=False)) == ""


def test_empty_text_blocks_ignored():
    msg = SimpleNamespace(content=[_text_block(""), _text_block("kept")])
    assert extract_message_text(msg) == "kept"


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    _run()
