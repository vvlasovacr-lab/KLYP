from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


TRAILING_CONNECTORS = frozenset(
    "а без бы в во для до за и из или либо к как на над не но о об от по под при про с со у чтобы "
    "это есть будет будут был была были является составит составляет равно около примерно всего "
    "мой моя мое мои твой твоя твое твои свой своя свое свою свои наш наша наше наши ваш ваша ваше ваши "
    "я ты он она оно мы вы они "
    "этот эта это эти каждый каждая каждое самое такой такая такое которые который которая "
    "лишь только себя заставит заставят заставляет заставляют получилось получится".split()
)

NUMBER_MODIFIERS = frozenset(
    "ноль один одна два две три четыре пять шесть семь восемь девять десять "
    "одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать "
    "семнадцать восемнадцать девятнадцать двадцать тридцать сорок пятьдесят "
    "шестьдесят семьдесят восемьдесят девяносто сто двести триста четыреста "
    "пятьсот шестьсот семьсот восемьсот девятьсот".split()
)
NUMBER_UNITS = frozenset(
    "ноль нуля нулей тысяча тысячи тысяч миллион миллиона миллионов миллиард "
    "миллиарда миллиардов процент процента процентов рубль рубля рублей доллар "
    "доллара долларов".split()
)
CLAUSE_BREAKERS = frozenset("а но не либо если когда зато однако".split())
PHRASE_BREAKERS = frozenset("в во на для про с со из к по у от до".split())


@dataclass(frozen=True)
class RetimeConfig:
    min_words: int = 2
    target_words: int = 3
    max_words: int = 4
    pause_threshold: float = 0.42


def _normalized(word: str) -> str:
    return word.lower().strip(".,!?;:—–-()[]{}\"'«»")


def _looks_like_modifier(token: str) -> bool:
    """Conservative Russian adjective check used only after a preposition."""
    return len(token) >= 4 and token.endswith((
        "ый", "ий", "ой", "ая", "яя", "ое", "ее", "ые", "ие",
        "ых", "их", "ым", "им", "ую", "юю", "ого", "его", "ому", "ему",
    ))


def _repair_semantic_boundaries(
    blocks: list[dict[str, Any]], config: RetimeConfig,
) -> list[dict[str, Any]]:
    """Move a short prepositional modifier to the following noun phrase.

    This turns a split such as ``говорить про богатых | родителей`` into
    ``говорить | про богатых родителей`` without increasing the word limit.
    """
    repaired = [dict(block) for block in blocks]
    for index in range(len(repaired) - 1):
        left = list(repaired[index]["words"])
        right = list(repaired[index + 1]["words"])
        if len(left) < config.min_words + 2 or len(right) + 2 > config.max_words:
            continue
        preposition = _normalized(str(left[-2]["word"]))
        modifier = _normalized(str(left[-1]["word"]))
        if preposition not in PHRASE_BREAKERS or not _looks_like_modifier(modifier):
            continue
        moved = left[-2:]
        repaired[index] = _make_block(left[:-2])
        repaired[index + 1] = _make_block(moved + right)
    return repaired


def _should_close(block: Sequence[dict[str, Any]], next_word: dict[str, Any] | None, config: RetimeConfig) -> bool:
    if len(block) < config.min_words:
        return False
    last = block[-1]
    punctuation = str(last["word"]).rstrip().endswith((".", "!", "?", ":", ";", ","))
    pause = next_word is not None and float(next_word["start"]) - float(last["end"]) >= config.pause_threshold
    at_target = len(block) >= config.target_words
    at_limit = len(block) >= config.max_words
    dangling = _normalized(str(last["word"])) in TRAILING_CONNECTORS and not punctuation
    leading = _normalized(str(block[0]["word"])) in TRAILING_CONNECTORS
    next_token = _normalized(str(next_word["word"])) if next_word is not None else ""
    number_pair = (
        next_word is not None
        and _normalized(str(last["word"])) in NUMBER_MODIFIERS
        and _normalized(str(next_word["word"])) in NUMBER_UNITS
    )
    clause_break = (len(block) >= 2 and next_token in CLAUSE_BREAKERS) or (len(block) >= 3 and next_token in PHRASE_BREAKERS)
    if clause_break and not dangling and not number_pair:
        return True
    if leading and len(block) < config.max_words and not punctuation:
        return False
    return not dangling and not number_pair and (punctuation or pause or at_target or at_limit or clause_break)


def retime_words(words: Sequence[dict[str, Any]], config: RetimeConfig | None = None) -> list[dict[str, Any]]:
    """Create readable phrase blocks while keeping exact original word timing."""
    config = config or RetimeConfig()
    blocks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for index, word in enumerate(words):
        current.append(dict(word))
        single_sentence_end = len(current) == 1 and str(current[0]["word"]).rstrip().endswith((".", "!", "?", ":", ";"))
        if single_sentence_end and blocks and len(blocks[-1]["words"]) >= 3:
            previous_words = list(blocks.pop()["words"])
            current.insert(0, previous_words.pop())
            while previous_words and _normalized(str(previous_words[-1]["word"])) in TRAILING_CONNECTORS:
                current.insert(0, previous_words.pop())
            if len(previous_words) < 2:
                current = previous_words + current
                previous_words = []
            if previous_words:
                blocks.append(_make_block(previous_words))
            blocks.append(_make_block(current))
            current = []
            continue
        following = words[index + 1] if index + 1 < len(words) else None
        if _should_close(current, following, config):
            blocks.append(_make_block(current))
            current = []
    if current:
        if len(current) == 1 and blocks and len(blocks[-1]["words"]) < config.max_words:
            merged = blocks.pop()["words"] + current
            blocks.append(_make_block(merged))
        else:
            blocks.append(_make_block(current))
    return _repair_semantic_boundaries(blocks, config)


def _make_block(words: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "start": round(float(words[0]["start"]), 3),
        "end": round(float(words[-1]["end"]), 3),
        "text": " ".join(str(word["word"]) for word in words),
        "words": list(words),
    }
