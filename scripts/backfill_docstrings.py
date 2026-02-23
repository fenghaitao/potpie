#!/usr/bin/env python3
"""
Backfill docstrings for nodes that have text but no docstring.
Runs inference only on the gap nodes — no need to re-parse.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app.core.database import get_db
from app.modules.parsing.knowledge_graph.inference_service import InferenceService


async def backfill(repo_id: str):
    db = next(get_db())
    svc = InferenceService(db)

    # Fetch only nodes with text but no docstring
    with svc.driver.session() as session:
        result = session.run(
            """
            MATCH (n:NODE {repoId: $repo_id})
            WHERE n.docstring IS NULL AND n.text IS NOT NULL AND n.text <> ''
            RETURN n.node_id AS node_id, n.text AS text,
                   n.file_path AS file_path, n.start_line AS start_line,
                   n.end_line AS end_line, n.name AS name
            """,
            repo_id=repo_id,
        )
        nodes = [dict(r) for r in result]

    print(f"Found {len(nodes)} nodes to backfill for project {repo_id}")

    batches = svc.batch_nodes(nodes, project_id=repo_id)
    print(f"Created {len(batches)} batches")

    # Process cached nodes first
    cached_nodes = [n for n in nodes if n.get("cached_inference")]
    for node in cached_nodes:
        node["project_id"] = repo_id
        await svc.update_neo4j_with_cached_inference(node)
    print(f"Applied {len(cached_nodes)} cache hits")

    from app.modules.parsing.knowledge_graph.inference_schema import DocstringResponse
    from app.modules.parsing.services.inference_cache_service import InferenceCacheService

    result_db = next(get_db())
    cache_service = InferenceCacheService(result_db)

    semaphore = asyncio.Semaphore(svc.parallel_requests)

    async def process_batch(batch, idx):
        async with semaphore:
            print(f"  Batch {idx+1}/{len(batches)} ({len(batch)} nodes)...")
            try:
                response = await svc.generate_response(batch, repo_id)
                if not isinstance(response, DocstringResponse):
                    response = await svc.generate_response(batch, repo_id)

                if isinstance(response, DocstringResponse):
                    response_by_id = {d.node_id: d for d in response.docstrings}
                    for req in batch:
                        meta = req.metadata or {}
                        doc = response_by_id.get(req.node_id)
                        if doc and cache_service and meta.get("should_cache") and meta.get("content_hash"):
                            try:
                                cache_service.store_inference(
                                    content_hash=meta["content_hash"],
                                    inference_data={"node_id": doc.node_id, "docstring": doc.docstring, "tags": doc.tags},
                                    project_id=repo_id,
                                    node_type=meta.get("node_type"),
                                    content_length=len(req.text),
                                    tags=doc.tags,
                                )
                            except Exception as e:
                                print(f"    Cache store failed: {e}")

                    processed = svc.process_chunk_responses(response, batch)
                    if processed:
                        svc.update_neo4j_with_docstrings(repo_id, processed)

                    # Fallback for skipped nodes
                    returned_ids = {d.node_id for d in response.docstrings}
                    skipped = [r for r in batch if r.node_id not in returned_ids]
                    if skipped:
                        print(f"    {len(skipped)} nodes skipped by LLM, writing fallbacks")
                        svc._write_fallback_docstrings(repo_id, skipped)

                return response
            except Exception as e:
                print(f"  Batch {idx} failed: {e}")
                return DocstringResponse(docstrings=[])

    tasks = [process_batch(b, i) for i, b in enumerate(batches)]
    await asyncio.gather(*tasks)

    cache_service.db.close()
    svc.close()
    db.close()

    # Final stats
    from neo4j import GraphDatabase
    from app.core.config_provider import config_provider
    neo4j_config = config_provider.get_neo4j_config()
    driver = GraphDatabase.driver(neo4j_config["uri"], auth=(neo4j_config["username"], neo4j_config["password"]))
    with driver.session() as s:
        print("\nFinal coverage:")
        for label in ["FUNCTION", "CLASS", "INTERFACE", "FILE"]:
            r = s.run(
                f"MATCH (n:{label} {{repoId: $r}}) RETURN count(n) as total, count(n.docstring) as with_doc",
                r=repo_id,
            ).single()
            pct = 100 * r["with_doc"] // max(r["total"], 1)
            print(f"  {label}: {r['with_doc']}/{r['total']} ({pct}%)")
    driver.close()


if __name__ == "__main__":
    repo_id = sys.argv[1] if len(sys.argv) > 1 else "0eaaac80-c722-c6ce-1a6f-b12fe103b6b0"
    asyncio.run(backfill(repo_id))
