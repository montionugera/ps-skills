#!/usr/bin/env python3
"""Build the Herdr tab label for a handoff: `<parent name> #N`, at most 16 characters.

The new tab replaces its parent, so it keeps the parent's name: the user named
that tab and looks for it in the sidebar. `#N` counts the handoffs in a chain.
Only a parent with a default name (a shell, `Handoff: …`, the bare project) falls
back to the topic, the doc title or the filename slug.
"""
import argparse
import re

DEFAULT_MAX = 16  # short enough to read at a glance in the sidebar
SEP = " · "  # older labels were `<project> · <topic>`; only the topic part is kept
ELLIPSIS = "…"
CLAUSE_SPLIT = re.compile(r",|;| — | \+ | then ")
SOURCE_PREFIX = re.compile(r"^(?:\[\d+\]\s+|⏳ relay → )*")  # in any order
GENERATION = re.compile(r"\s*#(\d+)$")
LEGACY_HANDOFF = re.compile(r"^Handoff:")
DEFAULT_NAMES = {"", "zsh", "-zsh", "bash", "-bash", "sh", "fish", "nu", "pwsh", "shell", "handoff"}


def _clean(text):
    return " ".join((text or "").split())


def first_clause(title):
    return CLAUSE_SPLIT.split(title, maxsplit=1)[0].strip()


def strip_project(topic, project):
    """Drop a leading repeat of the project name; `-` and space count as equal."""
    words = [re.escape(w) for w in re.split(r"[-\s]+", project) if w]
    if not words:
        return topic
    pattern = r"^" + r"[-\s]+".join(words) + r"(?![^\s\-:,;.])[\s\-:,;.]*"
    return re.sub(pattern, "", topic, count=1, flags=re.IGNORECASE).strip()


def parse_source(source_label):
    """Split a parent label into (name, its #N or None, is it a handoff tab, is it a default name)."""
    source = SOURCE_PREFIX.sub("", _clean(source_label))
    match = GENERATION.search(source)
    number = int(match.group(1)) if match else None
    name = GENERATION.sub("", source).strip()
    legacy_doc = bool(LEGACY_HANDOFF.match(name))
    legacy_pair = SEP in name
    if legacy_pair:
        name = name.split(SEP, 1)[1].strip()
    from_handoff = number is not None or legacy_doc or legacy_pair
    # Herdr names an unnamed tab with its bare number, for example "3".
    is_default = legacy_doc or name.isdigit() or name.lower() in DEFAULT_NAMES
    return name, number, from_handoff, is_default


def generation(source_label):
    """The next number in the chain, or None when the parent is not a handoff tab."""
    _, number, from_handoff, _ = parse_source(source_label)
    if number is not None:
        return number + 1
    return 2 if from_handoff else None


def choose_topic(topic, title, slug):
    if _clean(topic):
        return _clean(topic)
    title = _clean(title)
    if title and "<" not in title:
        return first_clause(title)
    return _clean((slug or "").replace("-", " "))


FILLER = {"a", "an", "and", "the", "to", "for", "of", "with", "on", "in", "-", "·", "|", "/", "&", "+"}
MIN_WORD = 5  # a word is never cut shorter than this when squeezing


def squeeze(text, room, project=""):
    """Fit text into room while keeping the words that tell tabs apart.

    In order: drop filler words and a repeated project name, join ticket keys
    (`ABC-123` -> `ABC123`), shorten the longest plain words one letter at a time
    down to 5 when that alone makes it fit, and only then cut with `…`.
    """
    if len(text) <= room:
        return text
    project_words = {w.lower() for w in re.split(r"[-\s]+", project) if w}
    words = [w for w in (w.strip(",;:") for w in text.split()) if w]
    if not words:
        return truncate(_clean(text), room)
    kept = [w for w in words if w and w.lower() not in FILLER and w.lower() not in project_words]
    words = kept or words
    words = [re.sub(r"^([A-Za-z]+)-(\d+)$", r"\1\2", w) for w in words]
    plain = " ".join(words)
    if len(plain) <= room:
        return plain
    # Shorten letters-only words after the first; ids and numbers stay whole.
    # Use it only when it makes everything fit: a shortened word and a cut together read worse.
    short = list(words)
    while len(" ".join(short)) > room:
        shrinkable = [i for i, w in enumerate(short) if i > 0 and w.isalpha() and len(w) > MIN_WORD]
        if not shrinkable:
            return truncate(plain, room)
        i = max(shrinkable, key=lambda j: (len(short[j]), j))
        short[i] = short[i][:-1]
    return " ".join(short)


def truncate(text, room):
    if len(text) <= room:
        return text
    if room <= 1:  # no space for more than the ellipsis
        return ""
    cut = text[: room - 1]
    if text[room - 1] == " " or cut.endswith(" "):  # the cut already ends on a whole word
        return cut.rstrip() + ELLIPSIS
    at_word = cut.rsplit(" ", 1)[0].rstrip() if " " in cut else cut
    # Back off to a whole word only when that keeps most of the room; otherwise cut inside the word.
    cut = at_word if len(at_word) * 3 >= (room - 1) * 2 else cut.rstrip()
    return cut + ELLIPSIS


def compose(project, topic=None, title=None, slug=None, source_label=None, max_len=DEFAULT_MAX):
    project = _clean(project)
    name, number, _, is_default = parse_source(source_label)
    if is_default or name.lower() == project.lower():
        name = strip_project(choose_topic(topic, title, slug), project) or project
        number = generation(source_label)
    else:
        # A named parent: this tab continues it, so it is at least #2.
        number = (number or 1) + 1
    suffix = f" #{number}" if number else ""
    body = squeeze(name, max_len - len(suffix), project)
    label = f"{body}{suffix}".strip() if body else ""
    # A cap too small for name and number keeps the name (or project) and drops the number.
    return label or squeeze(name, max_len, project) or truncate(project, max_len) or "handoff"[:max_len]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd-project", default="")
    parser.add_argument("--topic", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--slug", default="")
    parser.add_argument("--source-label", default="")
    parser.add_argument("--max", default=str(DEFAULT_MAX))
    args = parser.parse_args()
    max_len = int(args.max) if args.max.isdecimal() and int(args.max) > 0 else DEFAULT_MAX
    print(compose(args.cwd_project, args.topic, args.title, args.slug, args.source_label, max_len))


if __name__ == "__main__":
    main()
