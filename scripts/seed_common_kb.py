from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import delete, select

from openinterview_core.config import Settings
from openinterview_core.domain.kb.service import CommonKBProcessingService, SYSTEM_USER_ID
from openinterview_core.infra.blob import build_blob_storage
from openinterview_core.infra.db import Database
from openinterview_core.infra.db.common_kb_repository import SqlCommonKBRepository
from openinterview_core.infra.gateway_client import GatewayClient
from openinterview_core.infra.vector import ChromaVectorStore, InMemoryVectorStore
from openinterview_db import CommonKBItem, CommonKBItemTag


@dataclass(frozen=True)
class SeedItem:
    space: str
    source: str
    item_type: str
    category: str
    title: str
    question: str | None = None
    answer_outline: str | None = None
    content: str | None = None
    difficulty: int = 3
    tags: tuple[str, ...] = ()
    provenance: dict | None = None


SOURCES = {
    "leetcode_topics": {
        "space": "leetcode",
        "name": "LeetCode topic metadata",
        "source_type": "leetcode_index",
        "base_url": "https://github.com/fishercoder1534/Leetcode",
        "license": "metadata-only; no statements or solutions stored",
    },
    "system_design_primer": {
        "space": "system_design",
        "name": "System Design Primer",
        "source_type": "markdown",
        "base_url": "https://github.com/donnemartin/system-design-primer",
        "license": "CC BY 4.0",
    },
    "ddia_notes": {
        "space": "architecture",
        "name": "DDIA community notes",
        "source_type": "markdown",
        "base_url": "https://github.com/keyvanakbary/learning-notes",
        "license": "community summaries only",
    },
    "applied_ai_questions": {
        "space": "ai_design",
        "name": "Applied AI question bank",
        "source_type": "curated",
        "base_url": None,
        "license": "Open Interview original content",
    },
    "behavioral_star_bank": {
        "space": "behavioral",
        "name": "Behavioral STAR bank",
        "source_type": "curated",
        "base_url": None,
        "license": "Open Interview original content",
    },
}


SPACES = {
    "leetcode": "LeetCode / DSA",
    "system_design": "System Design",
    "ai_design": "AI Design",
    "architecture": "Architecture",
    "behavioral": "Behavioral",
}


ITEMS = [
    SeedItem("leetcode", "leetcode_topics", "topic", "algorithms", "Two Sum family", content="Hash-map complement lookup, pair counting, and sorted two-pointer variants. Focus on invariants, duplicate handling, and O(n) versus O(n log n) tradeoffs.", difficulty=2, tags=("array", "hashmap", "two-sum"), provenance={"upstream": "fishercoder1534/Leetcode", "stored": "title/difficulty/tags plus original concept note"}),
    SeedItem("leetcode", "leetcode_topics", "topic", "algorithms", "Graph traversal patterns", content="BFS for shortest unweighted paths and levels; DFS for connected components, cycle detection, and backtracking. Discuss visited state, queue/stack memory, and graph representation.", difficulty=3, tags=("graph", "bfs", "dfs"), provenance={"upstream": "fishercoder1534/Leetcode", "stored": "metadata plus concept note"}),
    SeedItem("leetcode", "leetcode_topics", "topic", "algorithms", "Dynamic programming state design", content="Define state, transition, base cases, iteration order, and compression. Compare top-down memoization with bottom-up tabulation using examples like knapsack, LIS, and grid paths.", difficulty=4, tags=("dp", "memoization", "tabulation"), provenance={"upstream": "fishercoder1534/Leetcode", "stored": "metadata plus concept note"}),
    SeedItem("leetcode", "leetcode_topics", "topic", "data_structures", "Heap and priority queue patterns", content="Use heaps for top-k, streaming medians, scheduling, and Dijkstra-style frontier ordering. Cover comparator choice, lazy deletion, and O(log n) update costs.", difficulty=3, tags=("heap", "priority-queue", "top-k"), provenance={"upstream": "fishercoder1534/Leetcode", "stored": "metadata plus concept note"}),
    SeedItem("system_design", "system_design_primer", "topic", "system_design", "Caching", content="Explain cache-aside, write-through, write-back, invalidation, TTLs, hot keys, consistency risks, and when a cache can become the system of record by accident.", difficulty=3, tags=("cache", "latency", "consistency"), provenance={"attribution": "donnemartin/system-design-primer", "license": "CC BY 4.0"}),
    SeedItem("system_design", "system_design_primer", "topic", "system_design", "Sharding", content="Discuss choosing a shard key, routing, rebalancing, fan-out queries, cross-shard transactions, and operational complexity. Call out when vertical partitioning or read replicas are simpler.", difficulty=4, tags=("sharding", "partitioning", "scale"), provenance={"attribution": "donnemartin/system-design-primer", "license": "CC BY 4.0"}),
    SeedItem("system_design", "system_design_primer", "topic", "system_design", "CAP and consistency", content="Frame CAP around network partitions, then explain strong consistency, eventual consistency, quorum reads/writes, monotonic reads, and product-level correctness requirements.", difficulty=4, tags=("cap", "consistency", "distributed-systems"), provenance={"attribution": "donnemartin/system-design-primer", "license": "CC BY 4.0"}),
    SeedItem("architecture", "ddia_notes", "topic", "architecture", "B-trees versus LSM trees", content="B-trees optimize read locality and range scans with in-place pages; LSM trees optimize write throughput through append/merge compaction. Compare write amplification, read amplification, space amplification, and operational tuning.", difficulty=4, tags=("storage", "btree", "lsm"), provenance={"attribution": "community DDIA summaries", "stored": "summary only, not book text"}),
    SeedItem("architecture", "ddia_notes", "topic", "architecture", "Replication tradeoffs", content="Leader-based replication is straightforward but can bottleneck writes; multi-leader helps availability but creates conflict handling; leaderless designs use quorums and hinted handoff with more complex reads.", difficulty=4, tags=("replication", "distributed-systems"), provenance={"attribution": "community DDIA summaries", "stored": "summary only, not book text"}),
    SeedItem("ai_design", "applied_ai_questions", "question", "ai_design", "RAG evaluation plan", question="How would you evaluate whether a RAG system is improving answer quality instead of just adding more context?", answer_outline="Cover retrieval recall, citation faithfulness, answer correctness, latency/cost, golden datasets, adversarial queries, human review, and regression gates.", difficulty=4, tags=("rag", "eval", "retrieval")),
    SeedItem("ai_design", "applied_ai_questions", "question", "ai_design", "Prompt versioning", question="How would you manage prompt changes in production?", answer_outline="Discuss versioned prompts, eval suites, rollout flags, model/provider compatibility, observability, rollback, and documenting intent behind changes.", difficulty=3, tags=("prompting", "eval", "ops")),
    SeedItem("ai_design", "applied_ai_questions", "question", "ai_design", "Agent tool safety", question="What guardrails do you put around an LLM agent with tools?", answer_outline="Mention typed tool schemas, authorization checks, dry-run/approval gates, bounded retries, audit logs, prompt-injection defenses, and idempotency.", difficulty=4, tags=("agents", "tool-use", "safety")),
    SeedItem("ai_design", "applied_ai_questions", "question", "ai_design", "Fine-tuning versus RAG", question="When would you fine-tune instead of using RAG?", answer_outline="Fine-tune for style, format, domain behavior, or compact task skills; use RAG for changing facts, attribution, access control, and source-grounded answers.", difficulty=3, tags=("fine-tuning", "rag")),
    SeedItem("ai_design", "applied_ai_questions", "question", "ai_design", "Inference throughput", question="How do KV cache, batching, and streaming affect LLM serving?", answer_outline="Explain prefill/decode phases, memory pressure, continuous batching, latency-throughput tradeoffs, streaming UX, and capacity metrics.", difficulty=4, tags=("inference", "kv-cache", "batching")),
    SeedItem("behavioral", "behavioral_star_bank", "question", "behavioral", "Disagreement with a peer", question="Tell me about a time you disagreed with a peer on a technical decision.", answer_outline="A strong STAR answer states context, the competing technical views, how evidence was gathered, how the decision was made, and what changed afterward.", difficulty=2, tags=("star", "collaboration")),
    SeedItem("behavioral", "behavioral_star_bank", "question", "behavioral", "Handling ambiguity", question="Tell me about a time you had to make progress with ambiguous requirements.", answer_outline="Look for explicit assumptions, stakeholder alignment, risk reduction, iterative delivery, and a concrete result.", difficulty=3, tags=("star", "ambiguity")),
    SeedItem("behavioral", "behavioral_star_bank", "question", "behavioral", "Owning a mistake", question="Tell me about a time you made a mistake in production.", answer_outline="A good answer avoids blame, explains detection and mitigation, communicates impact, identifies root cause, and shows a durable prevention step.", difficulty=3, tags=("star", "ownership", "incident")),
]


async def seed(kind: str) -> int:
    settings = Settings()  # type: ignore[call-arg]
    db = Database(settings.database_url)
    vector_store = InMemoryVectorStore()
    try:
        vector_store = ChromaVectorStore(settings.chroma_url)
    except Exception:
        pass
    gateway = GatewayClient(base_url=settings.gateway_url, service_token=settings.gateway_service_token)
    blob = build_blob_storage(settings)
    source_ids: dict[str, object] = {}
    item_ids = []
    try:
        async with db.sessionmaker() as s:
            repo = SqlCommonKBRepository(s)
            for key, name in SPACES.items():
                await repo.get_or_create_space(key=key, name=name)
            spaces = {sp.key: sp for sp in await repo.list_spaces()}
            for key, spec in SOURCES.items():
                if kind == "leetcode" and key != "leetcode_topics":
                    continue
                sp = spaces[spec["space"]]
                src = await repo.create_source(
                    space_id=sp.id,
                    key=key,
                    name=spec["name"],
                    source_type=spec["source_type"],
                    base_url=spec["base_url"],
                    license=spec["license"],
                    allowed_use={"store_text": True, "create_embeddings": True},
                )
                existing_ids = (
                    await s.execute(
                        select(CommonKBItem.id).where(CommonKBItem.source_id == src.id)
                    )
                ).scalars().all()
                if existing_ids:
                    await s.execute(
                        delete(CommonKBItemTag).where(
                            CommonKBItemTag.item_id.in_(existing_ids)
                        )
                    )
                    await s.execute(delete(CommonKBItem).where(CommonKBItem.id.in_(existing_ids)))
                await s.commit()
                source_ids[key] = src.id
            for item in ITEMS:
                if item.source not in source_ids:
                    continue
                sp = spaces[item.space]
                row = await repo.create_item(
                    space_id=sp.id,
                    source_id=source_ids[item.source],
                    document_id=None,
                    item_type=item.item_type,
                    category=item.category,
                    title=item.title,
                    question=item.question,
                    answer_outline=item.answer_outline,
                    content=item.content,
                    difficulty=item.difficulty,
                    provenance=item.provenance or {"source": item.source},
                    tags=list(item.tags),
                    status="ready",
                )
                item_ids.append(row.id)
        svc = CommonKBProcessingService(
            sessionmaker=db.sessionmaker,
            blob=blob,
            gateway=gateway,
            vector_store=vector_store,
        )
        await svc.embed_items(item_ids=item_ids, actor_user_id=SYSTEM_USER_ID)
        return len(item_ids)
    finally:
        await db.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["all", "leetcode"], default="all")
    args = parser.parse_args()
    count = asyncio.run(seed(args.kind))
    print(f"Seeded {count} common-KB items")


if __name__ == "__main__":
    main()
