"""
Evaluation script for RAG Librarian.
Calculates recall@k and MRR on a small gold dataset.
"""
import sys
import json
import argparse
import os
from pathlib import Path

# Add project root to python path to allow importing app module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.config.loader import load_config
from app.providers.factory import get_embedding_provider
from app.vector.qdrant_client import VectorService
from app.utils.logging import setup_logging

logger = setup_logging()

def evaluate(config_path: str, gold_data_path: str, top_k: int = 5):
    """
    Evaluate retrieval quality using recall@k and MRR.

    Args:
        config_path: Path to config file
        gold_data_path: Path to a JSON file containing queries and expected file_hash or file_name.
                        Format: [{"query": "...", "expected_file": "file.pdf", "corpus_id": "corpus1"}]
        top_k: Number of documents to retrieve for evaluation
    """
    if not os.path.exists(gold_data_path):
        logger.error(f"Gold data file not found: {gold_data_path}")
        sys.exit(1)

    try:
        with open(gold_data_path, 'r') as f:
            gold_data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load gold data: {e}")
        sys.exit(1)

    config = load_config(config_path)

    # Initialize embedder and vector service
    embedder = get_embedding_provider(
        name=config.models.embeddings.provider,
        base_url=config.models.embeddings.base_url,
        model=config.models.embeddings.model
    )

    vector_service = VectorService(config.vector_db.url, config.vector_db.collection_prefix)

    total_queries = len(gold_data)
    hits_at_k = 0
    mrr_sum = 0.0

    for item in gold_data:
        query = item.get("query")
        expected_file = item.get("expected_file")
        corpus_id = item.get("corpus_id")

        if not query or not expected_file or not corpus_id:
            logger.warning(f"Skipping malformed entry: {item}")
            total_queries -= 1
            continue

        # Embed query
        query_vector = embedder.embed([query])[0]

        # Search
        results = vector_service.search(corpus_id, query_vector, limit=top_k)

        # Check for expected file
        found_at_rank = -1
        for rank, result in enumerate(results):
            # Check payload for file name match
            payload = result.payload
            if payload and payload.get("file_name") == expected_file:
                found_at_rank = rank + 1
                break

        if found_at_rank > 0:
            hits_at_k += 1
            mrr_sum += 1.0 / found_at_rank
            logger.info(f"Query: '{query}' -> HIT at rank {found_at_rank}")
        else:
            logger.info(f"Query: '{query}' -> MISS")

    if total_queries > 0:
        recall_at_k = hits_at_k / total_queries
        mrr = mrr_sum / total_queries

        logger.info("\n--- Evaluation Results ---")
        logger.info(f"Total queries evaluated: {total_queries}")
        logger.info(f"Recall@{top_k}: {recall_at_k:.4f}")
        logger.info(f"MRR: {mrr:.4f}")
    else:
        logger.warning("No valid queries evaluated.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate RAG Librarian retrieval")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--data", required=True, help="Path to gold dataset JSON file")
    parser.add_argument("--k", type=int, default=5, help="Number of results to retrieve (k)")

    args = parser.parse_args()
    evaluate(args.config, args.data, args.k)
