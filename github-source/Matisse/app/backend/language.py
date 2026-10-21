"""Reply-language policy shared by web, CLI and autonomous generation."""

import re


class ReplyLanguageError(ValueError):
    pass


def validate_language(value):
    if not isinstance(value, str) or value not in {"zh", "en"}:
        raise ValueError("Language must be zh or en.")
    return value


def reply_language(settings):
    value = settings.get("language", "zh")
    return value if value in ("zh", "en") else "zh"


def language_instruction(settings):
    language = "English" if reply_language(settings) == "en" else "Simplified Chinese"
    instruction = (
        "\n\n[SELECTED REPLY LANGUAGE — OVERRIDES EARLIER STYLE LANGUAGE]\n"
        f"Write the user-facing reply in {language}. This applies to normal replies "
        "and self-initiated remarks, even if earlier persona instructions, memories, "
        "the conversation history or the latest user message use another language. "
        "Keep Matisse's personality, emotional continuity and relationship boundaries. "
        "Switch language naturally without announcing the switch in every reply. "
        "Code, proper names, exact quotations and translation examples may retain "
        "their required language. Keep JSON field names unchanged. Keep mood_label "
        "a short English state label. user_affect.evidence must still be an exact "
        "verbatim excerpt of the original user message; never translate that evidence."
    )
    if reply_language(settings) == "zh":
        instruction += (
            "\n本轮选定的回复语言是【简体中文】。即使上一轮回复或本轮用户消息是英文，"
            "本次 reply 也必须用自然的中文表达。不要沿用历史回复的英文语言；"
            "代码、专名、原文引语及翻译示例可以保留原文。"
        )
    return instruction


def validate_reply_language(reply, settings, user_message=""):
    """Catch a clearly wrong prose language, allowing quotes/code/translations.

    This is deliberately conservative, not a general-purpose language detector.
    Short names and bilingual examples should not trigger unnecessary retries.
    """
    if re.search(r"翻译|译成|\btranslat(?:e|ion)\b", user_message, re.IGNORECASE):
        return
    prose = re.sub(
        r'```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`]*`'
        r'|“[^”]*”|「[^」]*」|‘[^’]*’|"[^"\n]*"|(?m:^[ \t]*>[^\n]*)',
        "", reply,
    )
    chinese = len(re.findall(r"[\u4e00-\u9fff]", prose))
    latin = len(re.findall(r"[A-Za-z]", prose))
    if reply_language(settings) == "zh" and chinese <= 3 and latin >= 36:
        raise ReplyLanguageError("The reply is English, but Simplified Chinese is selected.")
    if reply_language(settings) == "en" and chinese >= 12 and chinese > latin * .45:
        raise ReplyLanguageError("The reply is Chinese, but English is selected.")
