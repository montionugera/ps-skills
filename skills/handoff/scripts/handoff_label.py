#!/usr/bin/env python3
"""Build the Herdr tab label for a handoff: `<project> · <topic> #N`.

The label has to answer two questions at a glance in a narrow sidebar: which
project is this, and what is it doing. `#N` counts the handoffs in a chain, so
the tab that replaced a closed one can be followed.
"""
import argparse
import re

DEFAULT_MAX = 40
SEP = " · "
ELLIPSIS = "…"
CLAUSE_SPLIT = re.compile(r",|;| — | \+ | then ")
PLUGIN_PREFIX = re.compile(r"^\[\d+\]\s+")
GENERATION = re.compile(r" #(\d+)$")


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


def choose_topic(topic, title, slug):
    if _clean(topic):
        return _clean(topic)
    title = _clean(title)
    if title and "<" not in title:
        return first_clause(title)
    return _clean((slug or "").replace("-", " "))


def generation(project, source_label):
    """The next number in the chain, or None when the source is not part of one."""
    source = PLUGIN_PREFIX.sub("", _clean(source_label))
    if source.startswith("Handoff: "):
        return 2
    if not project or not source.startswith(project + SEP):
        return None
    match = GENERATION.search(source)
    return int(match.group(1)) + 1 if match else 2


def truncate(topic, room):
    if len(topic) <= room:
        return topic
    if room <= 0:
        return ""
    cut = topic[: room - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0].rstrip()
    return cut + ELLIPSIS


def compose(project, topic=None, title=None, slug=None, source_label=None, max_len=DEFAULT_MAX):
    project = _clean(project)
    chosen = strip_project(choose_topic(topic, title, slug), project)
    number = generation(project, source_label)
    suffix = f" #{number}" if number else ""
    prefix = project + SEP if project and chosen else project
    room = max_len - len(prefix) - len(suffix)
    # A topic that would shrink below a word is noise, but the project always stays.
    body = truncate(chosen, room) if chosen else ""
    if chosen and not body:
        prefix = project
    label = f"{prefix}{body}{suffix}".strip()
    return label or "handoff"


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
