"""Convert Claude's Markdown output into Telegram-safe HTML.

The bot runs with parse_mode=HTML, but the LLM tends to emit Markdown
(`**bold**`, `- bullets`, `| tables |`). HTML mode renders those literally,
so we translate to the small subset of HTML Telegram supports and escape any
stray `<`, `>`, `&` that would otherwise break entity parsing.

Existing Telegram HTML tags (e.g. the recipe text, which is already HTML) are
preserved untouched, so the function is safe to apply to any reply.
"""
import re

# Tags Telegram renders; we keep these verbatim instead of escaping them.
_ALLOWED_TAGS = ("b", "strong", "i", "em", "u", "s", "code", "pre", "a", "blockquote")
_TAG_RE = re.compile(
    r"</?(?:" + "|".join(_ALLOWED_TAGS) + r")(?:\s[^>]*)?>",
    re.IGNORECASE,
)
_SENTINEL = "\x00{}\x00"


def md_to_telegram_html(text: str) -> str:
    if not text:
        return text

    # 1. Stash existing valid tags so escaping/markdown passes don't touch them.
    stash: list[str] = []

    def _stash(match: re.Match) -> str:
        stash.append(match.group(0))
        return _SENTINEL.format(len(stash) - 1)

    text = _TAG_RE.sub(_stash, text)

    # 2. Escape stray HTML special characters.
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 3. Block-level Markdown (tables, headings, rules, bullets).
    text = _convert_blocks(text)

    # 4. Inline Markdown.
    text = _convert_inline(text)

    # 5. Restore stashed tags.
    for i, tag in enumerate(stash):
        text = text.replace(_SENTINEL.format(i), tag)
    return text


def _convert_blocks(text: str) -> str:
    out: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            continue  # horizontal rule -> drop

        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(c == "" or re.fullmatch(r":?-+:?", c) for c in cells):
                continue  # separator row -> drop
            out.append(" — ".join(cells))
            continue

        heading = re.match(r"#{1,6}\s+(.*)", stripped)
        if heading:
            out.append(f"<b>{heading.group(1).strip()}</b>")
            continue

        lstripped = line.lstrip()
        bullet = re.match(r"[-*+]\s+(.*)", lstripped)
        if bullet:
            indent = line[: len(line) - len(lstripped)]
            out.append(f"{indent}• {bullet.group(1)}")
            continue

        out.append(line)
    return "\n".join(out)


def _convert_inline(text: str) -> str:
    text = re.sub(r"`([^`]+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<i>\1</i>", text)
    return text
