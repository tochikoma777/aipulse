from aipulse.core.hashing import (
    arxiv_id,
    canonical_url,
    content_hash,
    cross_source_key,
    hamming_distance,
    short_hash,
    simhash64,
)


def test_canonical_url_strips_tracking_and_trailing_slash():
    assert (
        canonical_url("https://Example.com:443/path/?utm_source=x&id=3")
        == "https://example.com/path?id=3"
    )
    assert canonical_url("https://example.com/path/") == "https://example.com/path"
    assert (
        canonical_url("https://example.com/a?ref=1&share_id=2&fbclid=3") == "https://example.com/a"
    )


def test_canonical_url_maps_papers_to_arxiv_key():
    # arXiv 与 HuggingFace Daily Papers 必须映射到同一 key，否则跨源去重要失效
    assert canonical_url("https://arxiv.org/abs/2501.12345") == "arxiv:2501.12345"
    assert canonical_url("https://arxiv.org/pdf/2501.12345v2") == "arxiv:2501.12345"
    assert canonical_url("https://huggingface.co/papers/2501.12345") == "arxiv:2501.12345"


def test_arxiv_id_and_cross_source_key():
    assert arxiv_id("https://arxiv.org/abs/2501.12345v3") == "2501.12345"
    assert arxiv_id("2501.12345") == "2501.12345"
    assert arxiv_id("not-a-paper") is None
    assert cross_source_key("https://github.com/owner/repo") == "repo:owner/repo"
    assert cross_source_key("https://github.com/owner/repo.git") == "repo:owner/repo"
    assert cross_source_key("https://example.com/x") is None


def test_content_hash_is_stable_and_source_scoped():
    assert content_hash("arxiv:2501.1", "arxiv") == content_hash("arxiv:2501.1", "arxiv")
    assert content_hash("arxiv:2501.1", "arxiv") != content_hash("arxiv:2501.1", "hf_papers")
    assert len(content_hash("x")) == 40
    assert len(short_hash("x")) == 8


def test_simhash_similarity():
    a = simhash64("OpenAI 发布 GPT-5，推理能力大幅提升")
    b = simhash64("OpenAI 发布 GPT-5，推理能力大幅提升")
    c = simhash64("OpenAI 发布 GPT-5，推理能力大幅提升！")
    d = simhash64("vLLM 发布新版，吞吐翻倍，显存占用下降")
    assert a == b
    assert hamming_distance(a, c) <= 3  # 微小改动应判定为同一事件
    assert hamming_distance(a, d) > 3  # 无关内容必须区分开
    assert simhash64("") == 0


def test_hamming_distance_counts_bits():
    assert hamming_distance(0b1010, 0b1001) == 2
    assert hamming_distance(7, 7) == 0
