#!/usr/bin/env python3
"""
Pull Ollama models required by RAGnificent.

Modes:
  - required: Pull the minimum local models needed for a working local setup
  - catalog:  Pull every Ollama model listed in models_catalog.yaml

OCR models configured in config.yaml are also included when they use an
Ollama-backed OCR backend.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Set

import yaml


DEFAULT_REQUIRED_MODELS = [
    "nomic-embed-text",
    "llama3",
]


def run_command(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def ensure_ollama_exists() -> None:
    if shutil.which("ollama") is None:
        print("Error: 'ollama' is not on PATH. Install Ollama first.", file=sys.stderr)
        raise SystemExit(1)

    try:
        result = run_command(["ollama", "--version"], check=True)
    except subprocess.CalledProcessError as exc:
        print("Error: Ollama is installed but not responding correctly.", file=sys.stderr)
        print(exc.stderr.strip(), file=sys.stderr)
        raise SystemExit(1)

    version = result.stdout.strip() or result.stderr.strip()
    print(f"Ollama detected: {version}")


def load_catalog(catalog_path: Path) -> dict:
    if not catalog_path.exists():
        print(f"Error: catalog file not found: {catalog_path}", file=sys.stderr)
        raise SystemExit(1)

    try:
        with catalog_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception as exc:
        print(f"Error reading catalog '{catalog_path}': {exc}", file=sys.stderr)
        raise SystemExit(1)


def load_yaml_file(path: Path, description: str) -> dict:
    if not path.exists():
        print(f"Warning: {description} not found: {path}", file=sys.stderr)
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception as exc:
        print(f"Warning: could not read {description} '{path}': {exc}", file=sys.stderr)
        return {}


def extract_ollama_models(catalog: dict) -> List[str]:
    discovered: List[str] = []

    for section_name in ("embedding", "llm"):
        section = catalog.get(section_name, {})
        ollama = section.get("ollama", {})
        models = ollama.get("models", [])
        if not isinstance(models, list):
            continue

        for item in models:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                discovered.append(model_id.strip())

    seen: Set[str] = set()
    ordered_unique: List[str] = []
    for model in discovered:
        if model not in seen:
            seen.add(model)
            ordered_unique.append(model)
    return ordered_unique


def extract_ocr_ollama_models(config: dict) -> List[str]:
    ocr = config.get("ocr", {})
    if not isinstance(ocr, dict):
        return []

    backend = str(ocr.get("backend", "")).strip().lower()
    if backend not in {"ollama", "ollama_glm_ocr", "glm_ocr"}:
        return []

    ollama = ocr.get("ollama", {})
    if not isinstance(ollama, dict):
        return []

    model = ollama.get("model")
    if isinstance(model, str) and model.strip():
        return [model.strip()]
    return []


def normalize_model_name(name: str) -> str:
    if name.endswith(":latest"):
        return name[:-7]
    return name


def get_installed_models() -> Set[str]:
    try:
        result = run_command(["ollama", "list"], check=True)
    except subprocess.CalledProcessError as exc:
        print("Error: failed to list installed Ollama models.", file=sys.stderr)
        print(exc.stderr.strip(), file=sys.stderr)
        raise SystemExit(1)

    installed: Set[str] = set()
    lines = result.stdout.splitlines()
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        first_col = line.split()[0]
        installed.add(normalize_model_name(first_col))
    return installed


def dedupe_keep_order(models: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for model in models:
        if model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered


def models_to_pull(mode: str, catalog_models: List[str], ocr_models: List[str]) -> List[str]:
    if mode == "required":
        return dedupe_keep_order([*DEFAULT_REQUIRED_MODELS, *ocr_models])
    if mode == "catalog":
        return dedupe_keep_order([*catalog_models, *ocr_models])
    print(f"Error: unknown mode '{mode}'", file=sys.stderr)
    raise SystemExit(1)


def pull_models(models: Iterable[str], installed: Set[str], force: bool) -> int:
    failures = 0

    for model in models:
        normalized = normalize_model_name(model)
        if normalized in installed and not force:
            print(f"[skip] {model} already installed")
            continue

        print(f"[pull] {model}")
        try:
            process = subprocess.Popen(
                ["ollama", "pull", model],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            assert process.stdout is not None
            for line in process.stdout:
                print(line.rstrip())

            rc = process.wait()
            if rc != 0:
                print(f"[fail] {model} exited with code {rc}", file=sys.stderr)
                failures += 1
            else:
                print(f"[ok]   {model}")
        except Exception as exc:
            print(f"[fail] {model}: {exc}", file=sys.stderr)
            failures += 1

    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull Ollama models for RAGnificent")
    parser.add_argument(
        "--mode",
        choices=["required", "catalog"],
        default="required",
        help="required = minimum local working set, catalog = all Ollama models in models_catalog.yaml",
    )
    parser.add_argument(
        "--catalog",
        default="models_catalog.yaml",
        help="Path to models_catalog.yaml",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml for OCR model discovery",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Pull even if the model already appears installed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which models would be pulled without pulling them",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_ollama_exists()

    catalog_path = Path(args.catalog).resolve()
    catalog = load_catalog(catalog_path)
    config_path = Path(args.config).resolve()
    config = load_yaml_file(config_path, "config file")
    catalog_models = extract_ollama_models(catalog)
    ocr_models = extract_ocr_ollama_models(config)
    if not catalog_models and not ocr_models:
        print("Error: no Ollama models found in the catalog.", file=sys.stderr)
        return 1

    target_models = models_to_pull(args.mode, catalog_models, ocr_models)
    installed = get_installed_models()

    print(f"\nSelected mode: {args.mode}")
    print(f"Catalog file: {catalog_path}")
    print(f"Config file: {config_path}")
    print("Models:")
    for model in target_models:
        marker = "installed" if normalize_model_name(model) in installed else "missing"
        print(f"  - {model} [{marker}]")

    if args.dry_run:
        print("\nDry run only. No models were pulled.")
        return 0

    print()
    failures = pull_models(target_models, installed, args.force)
    if failures:
        print(f"\nCompleted with {failures} failure(s).", file=sys.stderr)
        return 1

    print("\nAll requested models are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
