"""config.yaml as pydantic models: Ollama host and context window, generator, judge, embedding models,
loop limits and gate thresholds. The comments in config.yaml explain each value."""

from pathlib import Path

import yaml
from pydantic import BaseModel

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # metrics/prompt_gen


class GeneratorConfig(BaseModel):
    model: str
    temperature: float
    think: bool
    max_retries: int
    feedback_retries: int = 2


class JudgeConfig(BaseModel):
    model: str
    temperature: float
    think: bool


class EmbeddingConfig(BaseModel):
    semantic: str
    pragmatic: str
    pragmatic_instruction: str


class LoopConfig(BaseModel):
    n_per_category: int
    max_attempts_factor: int
    max_consecutive_rejects: int


class Thresholds(BaseModel):
    near_duplicate_sem: float
    sem_max: dict[str, float] = {}
    prag_min: float | None = None
    strict: bool = True
    stem_check: list[str] = []


class Config(BaseModel):
    ollama_host: str
    num_ctx: int
    generator: GeneratorConfig
    judge: JudgeConfig
    embeddings: EmbeddingConfig
    loop: LoopConfig
    thresholds: Thresholds


def load(path: Path = PACKAGE_ROOT / "config.yaml") -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
