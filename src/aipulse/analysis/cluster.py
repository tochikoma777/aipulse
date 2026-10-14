"""主题聚类（设计方案 §9.2，纯算法，零成本）。

TF-IDF + 余弦相似度（阈值 0.35 建边）→ 连通分量 = 主题。
- 中文用 jieba 分词，英文按词切分（坑 6：中文整句当一个 token 会让相似度失效）。
- **排除 `skip_cluster=True` 的条目**（title_only 中文源，22 字摘要会污染相似度矩阵）。
- 每个主题：hot_score 最高者为代表条目，TF-IDF top-5 为 keywords，name 用 top-3 拼接。
- 单点簇（成员数 < min_cluster_size）不落库，避免 1 条即 1 主题的噪音。
"""

from __future__ import annotations

import re
from datetime import date

import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from aipulse.core.config import load_scoring
from aipulse.core.logging import get_logger
from aipulse.store.models import Item, Topic
from aipulse.store.repo_items import topic_uid

log = get_logger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _text(item: Item) -> str:
    return f"{item.title or ''} {item.summary or ''}"[:1500].strip()


def tokenize(text: str) -> str:
    """把文本转成空格分隔的 token 串（供 TfidfVectorizer 默认分词）。"""
    if not text:
        return ""
    if _CJK_RE.search(text):
        return " ".join(w for w in jieba.cut(text) if w.strip())
    return " ".join(_WORD_RE.findall(text.lower()))


def _find(x: int, parent: list[int]) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(a: int, b: int, parent: list[int]) -> None:
    ra, rb = _find(a, parent), _find(b, parent)
    if ra != rb:
        parent[rb] = ra


def cluster_items(
    items: list[Item],
    *,
    day: date,
) -> tuple[list[Topic], dict[str, str | None]]:
    """对条目聚类。返回 (Topic 列表, {item_id: topic_id})。

    未聚类的条目不会出现在 mapping 里（调用方按需置 None）。
    """
    cfg = load_scoring().get("cluster", {})
    threshold = float(cfg.get("similarity_threshold", 0.35))
    min_size = int(cfg.get("min_cluster_size", 2))
    max_features = int(cfg.get("max_features", 20000))

    # 排除仅标题源 + 空文本
    candidates = [i for i in items if not i.skip_cluster and tokenize(_text(i))]
    if len(candidates) < min_size:
        log.info("cluster.too_few", n=len(candidates), msg="可聚类条目不足，跳过")
        return [], {}

    corpus = [tokenize(_text(i)) for i in candidates]
    vectorizer = TfidfVectorizer(max_features=max_features)
    matrix = vectorizer.fit_transform(corpus)
    sim = cosine_similarity(matrix)

    n = len(candidates)
    parent = list(range(n))
    for i in range(n):
        for j in range(i + 1, n):
            if sim[i][j] >= threshold:
                _union(i, j, parent)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(_find(i, parent), []).append(i)

    feature_names = vectorizer.get_feature_names_out()
    tfidf = matrix.toarray()

    topics: list[Topic] = []
    mapping: dict[str, str | None] = {}
    for indices in groups.values():
        if len(indices) < min_size:
            continue
        members = [candidates[i] for i in indices]
        avg = tfidf[indices].mean(axis=0)
        top_idx = avg.argsort()[::-1][:5]
        keywords = [str(feature_names[k]) for k in top_idx if avg[k] > 0]
        if not keywords:
            continue
        name = " ".join(keywords[:3])
        representative = max(members, key=lambda it: it.hot_score or 0.0)
        topic = Topic(
            id=topic_uid(name, day),
            name=name,
            keywords=keywords,
            representative_item_id=representative.id,
            item_count=len(members),
            date=day,
            avg_hot_score=round(
                sum(float(it.hot_score or 0.0) for it in members) / len(members), 4
            ),
            summary="",
        )
        topics.append(topic)
        for it in members:
            mapping[it.id] = topic.id

    log.info("cluster.done", topics=len(topics), clustered=len(mapping))
    return topics, mapping


__all__ = ["cluster_items", "tokenize"]
