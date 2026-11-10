"""Extract the author's layout from mixed stdout without changing raw evidence.

Only the known trailing comma before the small_items closing bracket is
normalized. All geometry, identities, quantities and summary counts are then
validated using the original instance. No algorithm source is modified.
"""
from collections import Counter
import json
import re
from experiments.adapt_guesser_output import adapt
from experiments.verify_mes_result import verify
from src.thpack import to_items


def extract_and_verify(text, inst):
    starts = list(re.finditer(r'\{\s*"type"\s*:\s*"output"', text))
    ends = list(re.finditer(r'\{\s*"remaining"\s*:', text))
    if len(starts) != 1 or len(ends) != 1 or starts[0].start() >= ends[0].start():
        raise ValueError("expected one author layout and one statistics object")
    fragment = text[starts[0].start():ends[0].start()].strip()
    normalized, count = re.subn(r',\s*(\]\s*\}\s*)$', r'\1', fragment)
    if count > 1:
        raise ValueError("unexpected normalization")
    payload = json.loads(normalized)
    stats = json.loads(text[ends[0].start():].strip())
    result = adapt(inst, payload)
    errors = verify(result, inst["box"], to_items(inst))
    if errors:
        raise ValueError("layout rejected: " + repr(errors))
    placed = Counter(b["name"] for b in result["boxes"])
    loaded = Counter()
    remaining = Counter()
    legal_ids = {int(tp["t"]) for tp in inst["types"]}
    for key, counter in (("loaded", loaded), ("remaining", remaining)):
        seen = set()
        for entry in stats[key]:
            if (not isinstance(entry, list) or len(entry) != 2 or
                    any(type(v) is not int for v in entry) or
                    entry[0] not in legal_ids or entry[1] <= 0 or entry[0] in seen):
                raise ValueError("invalid or duplicate author count")
            seen.add(entry[0])
            counter[f"T{entry[0]}"] = entry[1]
    if loaded != placed:
        raise ValueError("author loaded counts disagree with actual layout")
    expected = Counter({f"T{tp['t']}": tp["qty"] for tp in inst["types"]})
    if loaded + remaining != expected:
        raise ValueError("author remaining counts disagree with original quantities")
    if abs(stats["utilization"] - result["isd"]) > 1e-7:
        raise ValueError("author utilization differs from exact layout volume")
    return dict(result=result, author_statistics=stats,
                normalization=dict(trailing_array_comma_removed=bool(count)), errors=[])
