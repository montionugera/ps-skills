#!/usr/bin/env python3
"""Offline copy of `vault-engine context --query` scoring, for trying rules on the private sets.

Local only; reads private files at run time and prints counts, never prompt or note text.
  precision_sim.py freeze   write precision_prompts_300.json + precision_candidates.json (inputs for the labeller)
  precision_sim.py noise    print the query noise words (typed in >= 2% of prompts)
  precision_sim.py          score today's rule and the proposed rule on both sets

Not covered: prompts that never reach history.jsonl (task notifications, subagent briefs), pasted
text that history stores as a placeholder, and the hook's per-session budget (each prompt is scored alone).
"""
import collections, json, math, os, random, re, sys

HOME = os.path.expanduser("~")
STATE = HOME + "/.claude/state/vault-recall/"
INDEX = HOME + "/workspace/agentic-vault/_meta/indexes/knowledge.jsonl"
STOP = set("about after again also because been before being check could does doing done each from have here into just like make more most much need only other over please same should some such than that their them then there these they this those used using very want were what when where which while will with would your".split())
PRIVATE = {"pasitnusso", "joymify"}  # names kept out of the committed word list


def terms(s):
    seen, out = set(), []
    for t in re.split(r"[^a-z0-9]+", s.lower()):
        if len(t) >= 4 and t not in STOP and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def load_notes():
    notes = []
    for line in open(INDEX):
        e = json.loads(line)
        if e.get("id") and e.get("status") == "active":
            e["_title"] = set(terms(e.get("title", "")))
            e["_tags"] = set(terms(" ".join(e.get("tags") or [])))
            e["_body"] = set(e.get("terms") or [])
            notes.append(e)
    return notes


def typed_prompts():
    rows = [json.loads(line) for line in open(HOME + "/.claude/history.jsonl")]
    prompts = [(r.get("display") or "").strip() for r in rows]
    return [p for p in prompts if len(p) >= 12 and not p.startswith("/")]  # the hook's own filters


def noise_words(cut=0.02):
    prompts = typed_prompts()
    df = collections.Counter()
    for p in prompts:
        df.update(set(terms(p[:2000])))
    return sorted(t for t, c in df.items() if c / len(prompts) >= cut and t not in PRIVATE and not t.isdigit())


def rank(hits, limit):
    hits.sort(key=lambda h: (-h[0], tuple(-ord(c) for c in h[1]), h[2]))
    return [h[2] for h in hits[:limit] if limit] or [h[2] for h in hits]


def today(notes, query, limit=3):
    """context.go at 090cd63: title 3, tag 2, body 1; score >= 4 and one title or tag match."""
    hits = []
    for e in notes:
        score, strong = 0, False
        for t in terms(query[:2000]):
            w = 3 if t in e["_title"] else 2 if t in e["_tags"] else 1 if t in e["_body"] else 0
            score += w
            strong |= w >= 2
        if score >= 4 and strong:
            hits.append((score, e.get("updated", ""), e["id"]))
    return rank(hits, limit)


def proposed(notes, query, noise, limit=2, threshold=2.5, long_terms=80, head=20):
    """Long prompts keep their first terms; noise words and numbers score 0; each match is weighted by note rarity."""
    q = terms(query[:2000])
    if len(q) > long_terms:
        q = q[:head]
    q = [t for t in q if t not in noise and not t.isdigit()]
    df = collections.Counter()
    for e in notes:
        df.update(e["_title"] | e["_tags"] | e["_body"])
    top = math.log((len(notes) + 1) / 0.5)
    hits = []
    for e in notes:
        score, strong = 0.0, False
        for t in q:
            w = 3 if t in e["_title"] else 2 if t in e["_tags"] else 1 if t in e["_body"] else 0
            if w:
                score += w * math.log((len(notes) + 1) / (df[t] + 0.5)) / top
                strong |= w >= 2
        if score >= threshold and strong:
            hits.append((score, e.get("updated", ""), e["id"]))
    return rank(hits, limit)


def report(name, fn):
    recall_set = [json.loads(line) for line in open(STATE + "recall_set.jsonl") if line.strip()]
    precision_set = [json.loads(line) for line in open(STATE + "precision_set.jsonl")]
    recall = sum((not r["expected_id"] and not ids) or r["expected_id"] in ids for r in recall_set for ids in [fn(r["prompt"])])
    injected = relevant = prompts = served = 0
    for r in precision_set:
        ids = fn(r["prompt"])
        good = [i for i in ids if i in r["relevant_ids"]]
        injected += len(ids)
        relevant += len(good)
        prompts += bool(ids)
        served += bool(good)
    pct = 100 * relevant / injected if injected else 0
    print(f"{name}: recall {recall}/{len(recall_set)}, injecting prompts {prompts}/{len(precision_set)}, "
          f"injected {injected}, relevant {relevant} ({pct:.1f}%), prompts given a relevant note {served}")


def freeze():
    notes, prompts = load_notes(), typed_prompts()[-300:]
    json.dump(prompts, open(STATE + "precision_prompts_300.json", "w"))
    random.seed(41)
    out = []
    for n, p in enumerate(prompts):
        ids = today(notes, p, limit=0)
        if ids:
            random.shuffle(ids)  # the labeller must not see the ranking
            out.append({"n": n, "prompt": p[:2000], "candidate_ids": ids})
    json.dump(out, open(STATE + "precision_candidates.json", "w"), indent=1)
    print(len(prompts), "prompts,", len(out), "inject today,", sum(len(o["candidate_ids"]) for o in out), "pairs to label")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "freeze":
        freeze()
    elif cmd == "noise":
        print(" ".join(noise_words()))
    else:
        notes, noise = load_notes(), set(noise_words())
        report("today", lambda p: today(notes, p))
        report("proposed", lambda p: proposed(notes, p, noise))
