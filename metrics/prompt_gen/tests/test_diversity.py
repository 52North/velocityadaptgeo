from prompt_gen import seeds, typology
from prompt_gen.generator import used_openings, user_prompt
from prompt_gen.run import WrittenList

SEED = seeds.load("muenster_green_300m")


def fake_similarities(text, others):
    """Texts sharing their first word count as near-duplicates."""
    return [0.99 if t.split()[0] == text.split()[0] else 0.5 for t in others]


def _rec(prompt, accepted=False, reason=None):
    return {"prompt": prompt, "accepted": accepted, "reject_reason": reason}


def test_written_list_keeps_order_and_only_near_duplicate_rejections():
    w = WrittenList(fake_similarities, 0.97)
    w.add(_rec("A one", accepted=True))
    w.add(_rec("B two", reason="near_duplicate"))
    w.add(_rec("C three", reason="constraint:target"))
    w.add(_rec("D four", reason="relative:green_space"))
    w.add(_rec("E five", accepted=True))
    w.add(_rec(None, reason="generation_error: x"))
    assert w.entries == [("A one", "accepted"), ("B two", "rejected"), ("E five", "accepted")]


def test_written_list_skips_rejections_similar_to_a_listed_rejection():
    w = WrittenList(fake_similarities, 0.97)
    w.add(_rec("A one", accepted=True))
    w.add(_rec("B two", reason="near_duplicate"))
    w.add(_rec("B again", reason="near_duplicate"))  # near-duplicate of "B two": skipped
    w.add(_rec("A again", reason="near_duplicate"))  # near-duplicate of an accepted one only: listed
    assert [t for t, _ in w.entries] == ["A one", "B two", "A again"]


def test_written_list_is_append_only():
    w = WrittenList(fake_similarities, 0.97)
    seen = []
    for rec in [_rec("A", accepted=True), _rec("B x", reason="near_duplicate"), _rec("C", accepted=True)]:
        w.add(rec)
        assert w.entries[: len(seen)] == seen
        seen = list(w.entries)


def test_user_prompt_lists_tags_in_order_and_puts_the_target_last():
    target = typology.get("syntactic").types[0]
    p = user_prompt(SEED, [("first", "accepted"), ("second", "rejected")], target)
    assert p.index("[accepted] first") < p.index("[rejected: too similar to an accepted one] second")
    assert p.rstrip().endswith("Do not carry over the sentence structure of the paraphrases listed above.")
    assert f"apply only this operation: {target.name}" in p
    # Adding an entry only appends to the list; openings and target come after it, so the cacheable prefix is unchanged.
    longer = user_prompt(SEED, [("first", "accepted"), ("second", "rejected"), ("third", "accepted")], target)
    assert longer.startswith(p[: p.index("\n\nOpenings already used")])


def test_used_openings_are_unique_and_in_order():
    written = [("A visualization should be output that x", "accepted"), ("All areas in Münster, that y", "rejected"),
               ("A visualization should be output for z", "rejected")]
    assert used_openings(written) == ["A visualization should be", "All areas in Münster"]


def test_user_prompt_without_history_or_target():
    assert user_prompt(SEED, []) == f"Seed request:\n{SEED.text}"


def test_target_rotation_covers_every_type():
    category = typology.get("syntactic")
    picked = [category.types[(attempt - 1) % len(category.types)].name for attempt in range(1, 2 * len(category.types) + 1)]
    assert picked[: len(category.types)] == [t.name for t in category.types]
    assert picked[len(category.types):] == picked[: len(category.types)]


def test_near_duplicate_feedback_names_the_closest_accepted():
    from prompt_gen.run import near_duplicate_feedback
    assert near_duplicate_feedback("A x", [], fake_similarities, 0.97) is None
    assert near_duplicate_feedback("A x", ["B y"], fake_similarities, 0.97) is None
    msg = near_duplicate_feedback("A x", ["B y", "A z"], fake_similarities, 0.97)
    assert '"A z"' in msg and "clearly different structure" in msg


class ScriptedClient:
    """Returns the given paraphrases in order; records the conversation of each call."""

    def __init__(self, paraphrases):
        self.paraphrases = list(paraphrases)
        self.conversations = []

    def chat(self, model, messages, think, format, options):
        import json
        self.conversations.append([m["content"] for m in messages])
        content = json.dumps({"reasoning": "plan", "operations_applied": ["x"], "paraphrase": self.paraphrases.pop(0)})
        return type("R", (), {"message": type("M", (), {"content": content, "thinking": None})(), "eval_count": 10})()


def _generator(paraphrases, feedback_retries=2):
    from prompt_gen.config import GeneratorConfig
    from prompt_gen.generator import Generator
    g = Generator.__new__(Generator)
    g.config = GeneratorConfig(model="m", temperature=0.8, think=False, max_retries=3, feedback_retries=feedback_retries)
    g.strict, g.num_ctx = True, 8192
    g.client = ScriptedClient(paraphrases)
    return g


def _generate(g, feedback):
    from prompt_gen import examples
    from prompt_gen.run import EXAMPLES_PATH
    cat = typology.get("syntactic")
    return g.generate(cat, examples.load(EXAMPLES_PATH)[cat.key], SEED, [], sampling_seed=0, feedback=feedback)


def test_feedback_retry_sends_feedback_and_keeps_discarded_drafts():
    g = _generator(["dup one", "dup two", "fresh"])
    result = _generate(g, lambda text: "too similar" if text.startswith("dup") else None)
    assert result.paraphrase == "fresh"
    assert [d["prompt"] for d in result.discarded] == ["dup one", "dup two"]
    assert result.attempts == 3 and result.eval_tokens == 30
    # the third call saw both drafts and both feedback messages, in order
    assert g.client.conversations[2][-4:] == [g.client.conversations[2][-4], "too similar", g.client.conversations[2][-2], "too similar"]
    assert '"dup one"' in g.client.conversations[2][-4] and '"dup two"' in g.client.conversations[2][-2]


def test_feedback_retries_are_capped_and_the_last_draft_is_returned():
    g = _generator(["dup one", "dup two", "dup three"])
    result = _generate(g, lambda text: "too similar")
    assert result.paraphrase == "dup three"  # the caller rejects it without calling the judge
    assert len(result.discarded) == 2
