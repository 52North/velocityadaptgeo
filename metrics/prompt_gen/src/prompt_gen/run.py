"""The iterative generate -> score -> filter loop.

All state lives in out/<run_id>/candidates.jsonl: every candidate is appended as soon as it is
scored, and resuming a run re-reads that file. accepted.jsonl is rebuilt from it at the end.
embeddings.jsonl holds each paraphrase's semantic embedding, for prompt-review's live similarities.
"""

import base64
import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from prompt_gen import examples, stems, typology
from prompt_gen.config import PACKAGE_ROOT, Config
from prompt_gen.generator import GenerationError, Generator
from prompt_gen.judge import Judge
from prompt_gen.scoring import Scorer
from prompt_gen.seeds import Seed

OUT_DIR = PACKAGE_ROOT / "out"
EXAMPLES_PATH = PACKAGE_ROOT / "data" / "examples.yaml"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _append(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _model_digest(host: str, model: str) -> str | None:
    import ollama

    for m in ollama.Client(host=host).list().models:
        if m.model == model:
            return m.digest
    return None


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=PACKAGE_ROOT,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def stem_reason(result: stems.StemCheck) -> str | None:
    if result.passed:
        return None
    parts = []
    if result.new:
        parts.append("stem:" + ",".join(result.new))
    if result.missing:
        parts.append("missing:" + ",".join(result.missing))
    return "|".join(parts)


def near_duplicate_feedback(
    text: str, accepted: list[str], similarities, threshold: float
) -> str | None:
    """Feedback for the generator when a draft is a near-duplicate of an accepted paraphrase, else None."""
    if not accepted:
        return None
    sims = similarities(text, accepted)
    best = max(range(len(sims)), key=sims.__getitem__)
    if sims[best] <= threshold:
        return None
    return (
        f'Your paraphrase is too similar to this one, already written: "{accepted[best]}". Start again from the seed '
        "request and give the whole sentence a clearly different structure. Keep to the category's operations and "
        "to all hard constraints, and answer in the same JSON format."
    )


def is_near_duplicate(scores: dict, threshold: float) -> bool:
    return (
        scores["max_sem_same_category"] is not None
        and scores["max_sem_same_category"] > threshold
    )


def gate(cfg: Config, category: str, scores: dict, judgement) -> str | None:
    """Reject reason, or None if the candidate passes."""
    if not judgement.passed:
        return "constraint:" + ",".join(judgement.failed_ids)
    t = cfg.thresholds
    if judgement.relative_ids and t.strict:
        return "relative:" + ",".join(judgement.relative_ids)
    if not judgement.grammatical and t.strict:
        return "ungrammatical"
    if is_near_duplicate(scores, t.near_duplicate_sem):
        return "near_duplicate"
    if category in t.sem_max and scores["sem"] > t.sem_max[category]:
        return "too_similar_to_seed"
    if t.prag_min is not None and scores["prag"] < t.prag_min:
        return "intent_drift"
    return None


def closest(text: str, pool: list[dict], similarities) -> dict | None:
    """The record in `pool` whose paraphrase is most similar to `text`, as {"key", "prompt", "sem"},
    or None if no record in the pool has a paraphrase."""
    pool = [r for r in pool if r.get("prompt")]
    if not pool:
        return None
    sims = similarities(text, [r["prompt"] for r in pool])
    best = max(range(len(sims)), key=sims.__getitem__)
    r = pool[best]
    return {
        "key": f"{r['category']}#{r['attempt']}",
        "prompt": r["prompt"],
        "sem": float(sims[best]),
    }


def closest_matches(
    text: str, category: str, earlier: list[dict], similarities
) -> dict:
    """Both stored matches for a candidate, from the records written before it (in file order).

    closest_accepted: the closest gate-accepted paraphrase of the same category, i.e. what the
    near-duplicate gate compared against; its sem equals max_sem_same_category.
    closest_any: the closest gate-accepted paraphrase of any category. Rejected candidates are left out
    of both: they will not be used, so being close to one doesn't matter."""
    accepted = [r for r in earlier if r.get("accepted")]
    return {
        "closest_accepted": closest(
            text, [r for r in accepted if r["category"] == category], similarities
        ),
        "closest_any": closest(text, accepted, similarities),
    }


def backfill_closest(run_dir: Path, similarities) -> dict:
    """Add closest_accepted / closest_any to every record of an existing run.

    Copies candidates.jsonl to candidates.jsonl.bak first, then writes the new candidates.jsonl via a
    temp file. If a .bak already exists (an earlier backfill), it is kept as the untouched original, and
    the backfill only goes ahead if the current file differs from it in nothing but the closest_* fields,
    which are recomputed anyway. Must not run while a run is appending to the file.
    Returns counts, including mismatches between closest_accepted.sem and max_sem_same_category."""
    path = run_dir / "candidates.jsonl"
    backup = run_dir / "candidates.jsonl.bak"
    records = read_jsonl(path)
    if backup.exists():

        def strip(rs):
            return [
                {k: v for k, v in r.items() if not k.startswith("closest_")} for r in rs
            ]

        if strip(records) != strip(read_jsonl(backup)):
            raise FileExistsError(
                f"{backup} exists and candidates.jsonl differs from it in more than the closest_* fields; "
                "move the backup away first so it is never overwritten"
            )
        backup_status = "kept"
    else:
        shutil.copy2(path, backup)
        backup_status = "created"

    mismatches = []
    for i, r in enumerate(records):
        if not r.get("prompt"):
            continue
        r.update(closest_matches(r["prompt"], r["category"], records[:i], similarities))
        stored = r.get("max_sem_same_category")
        found = r["closest_accepted"]["sem"] if r["closest_accepted"] else None
        if (stored is None) != (found is None) or (
            stored is not None and abs(stored - found) > 1e-4
        ):
            mismatches.append(
                f"{r['category']}#{r['attempt']}: stored {stored}, recomputed {found}"
            )

    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return {
        "records": len(records),
        "with_prompt": sum(1 for r in records if r.get("prompt")),
        "mismatches": mismatches,
        "backup": backup_status,
    }


def embedding_line(key: str, text: str, vector, model: str) -> dict:
    """One line of embeddings.jsonl: the normalized vector as base64 of little-endian float32 (exact,
    and half the size of decimal numbers), with the text's hash so a reader can check it still matches."""
    v = np.asarray(vector, dtype="<f4")
    return {
        "key": key,
        "text_sha1": hashlib.sha1(text.encode("utf-8")).hexdigest(),
        "model": model,
        "dim": int(v.shape[0]),
        "vector": base64.b64encode(v.tobytes()).decode("ascii"),
    }


def backfill_embeddings(run_dir: Path, embed, model: str) -> dict:
    """Append an embeddings.jsonl line for every candidate with a paraphrase that has none yet.
    `embed(texts) -> array of normalized vectors`. Only appends; candidates.jsonl isn't touched.
    Must not run while a run is appending to the same folder."""
    path = run_dir / "embeddings.jsonl"
    present = {line["key"] for line in read_jsonl(path)}
    todo = [
        r
        for r in read_jsonl(run_dir / "candidates.jsonl")
        if r.get("prompt") and f"{r['category']}#{r['attempt']}" not in present
    ]
    vectors = embed([r["prompt"] for r in todo]) if todo else []
    for r, v in zip(todo, vectors):
        _append(
            path,
            embedding_line(f"{r['category']}#{r['attempt']}", r["prompt"], v, model),
        )
    return {"written": len(todo), "present": len(present)}


class WrittenList:
    """Paraphrases already written in one category, shown to the generator so it doesn't repeat itself.

    Holds accepted paraphrases and near-duplicate rejections, tagged, in the order they were written.
    A near-duplicate rejection is skipped if it is itself a near-duplicate of a rejection already listed,
    so the list grows with distinct attempts only. Entries are only ever appended, which keeps the
    generator prompt's prefix cacheable.
    """

    def __init__(self, similarities, threshold: float):
        self.similarities = (
            similarities  # (text, others) -> list of cosine similarities
        )
        self.threshold = threshold
        self.entries: list[tuple[str, str]] = []

    def add(self, record: dict) -> None:
        text = record.get("prompt")
        if not text:
            return
        if record.get("accepted"):
            self.entries.append((text, "accepted"))
        elif record.get("reject_reason") == "near_duplicate":
            rejected = [t for t, tag in self.entries if tag == "rejected"]
            if rejected and max(self.similarities(text, rejected)) > self.threshold:
                return
            self.entries.append((text, "rejected"))


class Run:
    def __init__(self, cfg: Config, seed: Seed, run_id: str | None = None):
        self.cfg = cfg
        self.seed = seed
        self.run_id = run_id or f"{datetime.now():%Y%m%d-%H%M%S}_{seed.id}"
        self.dir = OUT_DIR / self.run_id
        self.candidates_path = self.dir / "candidates.jsonl"
        self.embeddings_path = self.dir / "embeddings.jsonl"
        self.examples = examples.load(EXAMPLES_PATH)

    def _write_config(self, categories: list[str], n: int) -> None:
        """Config and code snapshot. The first session writes config.json and code/; each resumed session
        adds config_<time>.json and code_<time>/, since the code may have changed in between."""
        suffix = (
            ""
            if not (self.dir / "config.json").exists()
            else f"_{datetime.now():%Y%m%d-%H%M%S}"
        )
        path = self.dir / f"config{suffix}.json"
        snapshot = {
            "run_id": self.run_id,
            "started": datetime.now().isoformat(timespec="seconds"),
            "git_commit": _git_commit(),
            "seed": asdict(self.seed),
            "categories": categories,
            # All categories in order, so prompt-review knows them without importing this package.
            "typology": [{"key": c.key, "name": c.name} for c in typology.CATEGORIES],
            "n_per_category": n,
            "config": self.cfg.model_dump(),
            "model_digests": {
                m: _model_digest(self.cfg.ollama_host, m)
                for m in {self.cfg.generator.model, self.cfg.judge.model}
            },
            "examples_yaml": EXAMPLES_PATH.read_text(encoding="utf-8"),
        }
        path.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        # The code may not be committed yet, so keep an exact copy of what produced this run.
        shutil.copytree(
            PACKAGE_ROOT / "src" / "prompt_gen",
            self.dir / f"code{suffix}",
            ignore=shutil.ignore_patterns("__pycache__"),
        )

    def execute(
        self, categories: list[str], n: int, hours: float | None = None
    ) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._write_config(categories, n)
        history = read_jsonl(self.candidates_path)
        if history:
            print(f"Resuming {self.run_id}: {len(history)} candidates already scored")

        print("Loading models...", flush=True)
        generator = Generator(
            self.cfg.generator,
            self.cfg.ollama_host,
            self.cfg.thresholds.strict,
            self.cfg.num_ctx,
        )
        judge = Judge(self.cfg.judge, self.cfg.ollama_host, self.cfg.num_ctx)
        scorer = Scorer(self.cfg.embeddings)

        loop = self.cfg.loop
        durations = [c["duration_s"] for c in history if "duration_s" in c]
        deadline = time.monotonic() + hours * 3600 if hours else None
        for cat_index, key in enumerate(categories):
            # Equal share of the remaining time; time a category doesn't use rolls over to the next.
            # Categories run one after another so Ollama can reuse the cached prompt prefix.
            budget_end = (
                time.monotonic()
                + (deadline - time.monotonic()) / (len(categories) - cat_index)
                if deadline
                else None
            )
            category = typology.get(key)
            mine = [c for c in history if c["category"] == key]
            accepted = [c["prompt"] for c in mine if c["accepted"]]
            written = WrittenList(
                scorer.semantic_similarities, self.cfg.thresholds.near_duplicate_sem
            )
            for c in mine:
                written.add(c)
            attempts = len(mine)
            consecutive = (
                0  # per session: a resumed run gets a fresh chance in every category
            )
            max_attempts = loop.max_attempts_factor * n

            while (
                len(accepted) < n
                and attempts < max_attempts
                and consecutive < loop.max_consecutive_rejects
                and (budget_end is None or time.monotonic() < budget_end)
            ):
                attempts += 1
                started = time.monotonic()
                target = category.types[(attempts - 1) % len(category.types)]
                record = {
                    "seed_id": self.seed.id,
                    "category": key,
                    "attempt": attempts,
                    "target_operation": target.name,
                }
                try:
                    g = generator.generate(
                        category,
                        self.examples[key],
                        self.seed,
                        written.entries,
                        sampling_seed=cat_index * 1000 + attempts * 10,
                        target=target,
                        feedback=lambda text, accepted=accepted: (
                            near_duplicate_feedback(
                                text,
                                accepted,
                                scorer.semantic_similarities,
                                self.cfg.thresholds.near_duplicate_sem,
                            )
                        ),
                    )
                except GenerationError as e:
                    record.update(
                        prompt=None,
                        accepted=False,
                        reject_reason=f"generation_error: {e}",
                    )
                else:
                    generation: dict[str, Any] = {
                        "prompt": g.paraphrase,
                        "operations_applied": g.operations_applied,
                        "reasoning": g.reasoning,
                        "sampling_seed": g.sampling_seed,
                        "generation_attempts": g.attempts,
                        "eval_tokens": g.eval_tokens,
                        "discarded": g.discarded,
                    }
                    generation.update(
                        closest_matches(
                            g.paraphrase, key, history, scorer.semantic_similarities
                        )
                    )
                    stem_result = (
                        stems.check(self.seed.text, g.paraphrase)
                        if key in self.cfg.thresholds.stem_check
                        else None
                    )
                    if stem_result is not None:
                        generation["stems"] = {
                            "new": list(stem_result.new),
                            "missing": list(stem_result.missing),
                        }
                    if stem_result is not None and not stem_result.passed:
                        # Deterministic and instant: skip the embeddings and the ~65 s judge call.
                        record.update(
                            generation,
                            accepted=False,
                            reject_reason=stem_reason(stem_result),
                            relative=[],
                        )
                    else:
                        others = [
                            c["prompt"]
                            for c in history
                            if c["accepted"] and c["category"] != key
                        ]
                        scores = scorer.score(
                            g.paraphrase, self.seed.text, accepted, others
                        )
                        if is_near_duplicate(
                            scores, self.cfg.thresholds.near_duplicate_sem
                        ):
                            # Still a near-duplicate after the feedback retries: no need to spend ~105 s on the judge.
                            record.update(
                                generation,
                                accepted=False,
                                reject_reason="near_duplicate",
                                relative=[],
                                **scores,
                            )
                        else:
                            judgement = judge.check(
                                self.seed, category, g.paraphrase, stem_result
                            )
                            reason = gate(self.cfg, key, scores, judgement)
                            record.update(
                                generation,
                                accepted=reason is None,
                                reject_reason=reason,
                                relative=judgement.relative_ids,
                                ungrammatical=not judgement.grammatical,
                                **scores,
                                judge=judgement.model_dump(),
                            )
                record["duration_s"] = round(time.monotonic() - started, 1)
                _append(self.candidates_path, record)
                if record[
                    "prompt"
                ]:  # the vector is cached from the similarity checks above
                    vector = scorer.semantic.embed([record["prompt"]])[0]
                    _append(
                        self.embeddings_path,
                        embedding_line(
                            f"{key}#{attempts}",
                            record["prompt"],
                            vector,
                            self.cfg.embeddings.semantic,
                        ),
                    )
                history.append(record)
                written.add(record)
                durations.append(record["duration_s"])

                if record["accepted"]:
                    accepted.append(record["prompt"])
                    consecutive = 0
                else:
                    consecutive += 1
                self._progress(
                    key, accepted, n, attempts, record, durations, categories, cat_index
                )

            if len(accepted) < n:
                if budget_end is not None and time.monotonic() >= budget_end:
                    why = "time budget"
                elif attempts >= max_attempts:
                    why = "max attempts"
                else:
                    why = f"{consecutive} rejects in a row"
                print(f"  ! {key}: stopped at {len(accepted)}/{n} accepted ({why})")

        self.write_accepted()

    def _progress(
        self, key, accepted, n, attempts, record, durations, categories, cat_index
    ) -> None:
        mean = sum(durations) / len(durations)
        remaining = (n - len(accepted)) + n * (len(categories) - cat_index - 1)
        status = (
            "accepted"
            if record["accepted"]
            else f"rejected ({record['reject_reason']})"
        )
        sims = (
            f" sem={record['sem']:.3f} prag={record['prag']:.3f}"
            if "sem" in record
            else ""
        )
        tag = f" relative={record['relative']}" if record.get("relative") else ""
        tag += " ungrammatical" if record.get("ungrammatical") else ""
        print(
            f"[{key} {len(accepted)}/{n}, attempt {attempts}] {status}{sims}{tag} "
            f"{record['duration_s']:.0f}s | ETA at least {remaining * mean / 60:.0f} min",
            flush=True,
        )

    def write_accepted(self) -> Path:
        """accepted.jsonl in the agent runner's prompt format, plus metadata fields."""
        path = self.dir / "accepted.jsonl"
        counters: dict[str, int] = {}
        with path.open("w", encoding="utf-8") as f:
            for c in read_jsonl(self.candidates_path):
                if not c["accepted"]:
                    continue
                counters[c["category"]] = counters.get(c["category"], 0) + 1
                f.write(
                    json.dumps(
                        {
                            "label": f"{c['seed_id']}/{c['category']}-{counters[c['category']]}",
                            "prompt": c["prompt"],
                            "seed_id": c["seed_id"],
                            "category": c["category"],
                            "relative": c["relative"],
                            "ungrammatical": c.get("ungrammatical", False),
                            "sem": c["sem"],
                            "prag": c["prag"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        return path
