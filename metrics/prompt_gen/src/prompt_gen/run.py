"""The iterative generate -> score -> filter loop.

All state lives in out/<run_id>/candidates.jsonl: every candidate is appended as soon as it is
scored, and resuming a run re-reads that file. accepted.jsonl is rebuilt from it at the end.
"""

import json
import shutil
import subprocess
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from prompt_gen import examples, typology
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
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=PACKAGE_ROOT).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def gate(cfg: Config, category: str, scores: dict, judgement) -> str | None:
    """Reject reason, or None if the candidate passes."""
    if not judgement.passed:
        return "constraint:" + ",".join(judgement.failed_ids)
    t = cfg.thresholds
    if judgement.relative_ids and not t.accept_relative:
        return "relative:" + ",".join(judgement.relative_ids)
    if scores["max_sem_same_category"] is not None and scores["max_sem_same_category"] > t.near_duplicate_sem:
        return "near_duplicate"
    if category in t.sem_max and scores["sem"] > t.sem_max[category]:
        return "too_similar_to_seed"
    if t.prag_min is not None and scores["prag"] < t.prag_min:
        return "intent_drift"
    return None


class Run:
    def __init__(self, cfg: Config, seed: Seed, run_id: str | None = None):
        self.cfg = cfg
        self.seed = seed
        self.run_id = run_id or f"{datetime.now():%Y%m%d-%H%M%S}_{seed.id}"
        self.dir = OUT_DIR / self.run_id
        self.candidates_path = self.dir / "candidates.jsonl"
        self.examples = examples.load(EXAMPLES_PATH)

    def _write_config(self, categories: list[str], n: int) -> None:
        path = self.dir / "config.json"
        if path.exists():
            return
        snapshot = {
            "run_id": self.run_id,
            "started": datetime.now().isoformat(timespec="seconds"),
            "git_commit": _git_commit(),
            "seed": asdict(self.seed),
            "categories": categories,
            "n_per_category": n,
            "config": self.cfg.model_dump(),
            "model_digests": {
                m: _model_digest(self.cfg.ollama_host, m) for m in {self.cfg.generator.model, self.cfg.judge.model}
            },
            "examples_yaml": EXAMPLES_PATH.read_text(encoding="utf-8"),
        }
        path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        # The code may not be committed yet, so keep an exact copy of what produced this run.
        shutil.copytree(PACKAGE_ROOT / "src" / "prompt_gen", self.dir / "code", ignore=shutil.ignore_patterns("__pycache__"))

    def execute(self, categories: list[str], n: int, hours: float | None = None) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._write_config(categories, n)
        history = read_jsonl(self.candidates_path)
        if history:
            print(f"Resuming {self.run_id}: {len(history)} candidates already scored")

        print("Loading models...", flush=True)
        generator = Generator(self.cfg.generator, self.cfg.ollama_host, self.cfg.thresholds.accept_relative, self.cfg.num_ctx)
        judge = Judge(self.cfg.judge, self.cfg.ollama_host, self.cfg.num_ctx)
        scorer = Scorer(self.cfg.embeddings)

        loop = self.cfg.loop
        durations = [c["duration_s"] for c in history if "duration_s" in c]
        deadline = time.monotonic() + hours * 3600 if hours else None
        for cat_index, key in enumerate(categories):
            # Equal share of the remaining time; time a category doesn't use rolls over to the next.
            # Categories run one after another so Ollama can reuse the cached prompt prefix.
            budget_end = (
                time.monotonic() + (deadline - time.monotonic()) / (len(categories) - cat_index) if deadline else None
            )
            category = typology.get(key)
            mine = [c for c in history if c["category"] == key]
            accepted = [c["prompt"] for c in mine if c["accepted"]]
            attempts = len(mine)
            consecutive = 0
            for c in reversed(mine):
                if c["accepted"]:
                    break
                consecutive += 1
            max_attempts = loop.max_attempts_factor * n

            while (
                len(accepted) < n
                and attempts < max_attempts
                and consecutive < loop.max_consecutive_rejects
                and (budget_end is None or time.monotonic() < budget_end)
            ):
                attempts += 1
                started = time.monotonic()
                record = {"seed_id": self.seed.id, "category": key, "attempt": attempts}
                try:
                    g = generator.generate(category, self.examples[key], self.seed, accepted, sampling_seed=cat_index * 1000 + attempts * 10)
                except GenerationError as e:
                    record.update(prompt=None, accepted=False, reject_reason=f"generation_error: {e}")
                else:
                    others = [c["prompt"] for c in history if c["accepted"] and c["category"] != key]
                    scores = scorer.score(g.paraphrase, self.seed.text, accepted, others)
                    judgement = judge.check(self.seed, category, g.paraphrase)
                    reason = gate(self.cfg, key, scores, judgement)
                    record.update(
                        prompt=g.paraphrase,
                        accepted=reason is None,
                        reject_reason=reason,
                        relative=judgement.relative_ids,
                        **scores,
                        judge=judgement.model_dump(),
                        operations_applied=g.operations_applied,
                        reasoning=g.reasoning,
                        sampling_seed=g.sampling_seed,
                        generation_attempts=g.attempts,
                        eval_tokens=g.eval_tokens,
                    )
                record["duration_s"] = round(time.monotonic() - started, 1)
                _append(self.candidates_path, record)
                history.append(record)
                durations.append(record["duration_s"])

                if record["accepted"]:
                    accepted.append(record["prompt"])
                    consecutive = 0
                else:
                    consecutive += 1
                self._progress(key, accepted, n, attempts, record, durations, categories, cat_index)

            if len(accepted) < n:
                if budget_end is not None and time.monotonic() >= budget_end:
                    why = "time budget"
                elif attempts >= max_attempts:
                    why = "max attempts"
                else:
                    why = f"{consecutive} rejects in a row"
                print(f"  ! {key}: stopped at {len(accepted)}/{n} accepted ({why})")

        self.write_accepted()

    def _progress(self, key, accepted, n, attempts, record, durations, categories, cat_index) -> None:
        mean = sum(durations) / len(durations)
        remaining = (n - len(accepted)) + n * (len(categories) - cat_index - 1)
        status = "accepted" if record["accepted"] else f"rejected ({record['reject_reason']})"
        sims = f" sem={record['sem']:.3f} prag={record['prag']:.3f}" if "sem" in record else ""
        tag = f" relative={record['relative']}" if record.get("relative") else ""
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
                f.write(json.dumps({
                    "label": f"{c['seed_id']}/{c['category']}-{counters[c['category']]}",
                    "prompt": c["prompt"],
                    "seed_id": c["seed_id"],
                    "category": c["category"],
                    "relative": c["relative"],
                    "sem": c["sem"],
                    "prag": c["prag"],
                }, ensure_ascii=False) + "\n")
        return path
