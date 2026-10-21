"""Conservative checks for degenerate prose, shared by replies and thoughts."""

import re


class ReplyQualityError(ValueError):
    pass


_CODE = re.compile(r"```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\r\n]*`")
_LOOP = re.compile(r"(?P<unit>.{1,160}?)(?P=unit){3,}", re.DOTALL)


def has_runaway_repetition(text):
    """Detect long consecutive loops, preserving normal emphasis and code.

    Short units need at least eight copies and 32 letters; longer phrases
    need at least four copies and 64 letters. Punctuation/digits alone do
    not count. These bounds deliberately tolerate ordinary repeated words.
    """
    prose = re.sub(r"\s+", " ", _CODE.sub(" ", text))
    for match in _LOOP.finditer(prose):
        unit = match.group("unit")
        copies = len(match.group()) // len(unit)
        letters = sum(character.isalpha() for character in match.group())
        if len(unit) <= 4:
            if copies >= 8 and letters >= 32:
                return True
        elif letters >= 64:
            return True
    return False


def validate_reply(text):
    if has_runaway_repetition(text):
        raise ReplyQualityError("Model reply contains runaway repetition.")
