"""Conversation context: follow-ups, history-aware retrieval, the history window,
the background summary, and prompt-cache accounting."""

from sqlalchemy import select

from app.core import context as ctx
from app.core import pipeline
from app.core.policy_config import load_policy, save_policy
from app.core.providers.anthropic_adapter import build_kwargs
from app.core.providers.base import ChatRequest, ModelSpec
from app.core.providers.mock import MockProvider
from app.models import Attempt, Document, DocumentChunk, User

CNIC = "42101-1234567-1"


def root_user(db) -> User:
    return db.execute(select(User)).scalars().first()


def set_policy(db, **changes):
    save_policy(db, load_policy(db).model_copy(update=changes), root_user(db))


def convo(*turns: str) -> list[dict]:
    roles = ["user", "assistant"]
    return [{"role": roles[i % 2], "content": t} for i, t in enumerate(turns)]


def run(db, messages, **kwargs):
    request = pipeline.RouteRequest.for_user(root_user(db), messages, **kwargs)
    plan = pipeline.prepare(db, request)
    return plan, pipeline.run_to_completion(plan)


# --------------------------------------------------------------- follow-ups


def test_follow_up_detection():
    q, a = "How does dropout reduce overfitting?", "Dropout randomly disables neurons during training."
    for text in ["Why?", "Make it shorter", "Why does it help?", "What about batch normalization?",
                 "Is it better than weight decay?", "Explain that in simpler terms", "Give an example"]:
        assert ctx.is_follow_up(text, q, a), text
    for text in ["What is BERT?", "Summarise the attention mechanism in transformers for machine translation",
                 "How does BERT pretraining differ from GPT pretraining on large corpora?"]:
        assert not ctx.is_follow_up(text, q, a), text
    assert not ctx.is_follow_up("Why?", "", "")  # nothing to follow


def test_retrieval_query_borrows_earlier_terms_only_for_follow_ups():
    history = convo("How does dropout regularise networks?", "It disables random neurons.")
    follow = ctx.retrieval_query("Why does it work?", ctx.analyse_turn("Why does it work?", history))
    assert follow["dropout"] == ctx.PREVIOUS_QUESTION_WEIGHT and follow["work"] == 1.0
    fresh = ctx.retrieval_query("What is BERT pretraining?", ctx.analyse_turn("What is BERT pretraining?", history))
    assert "dropout" not in fresh


def _add_doc(db, texts):
    user = root_user(db)
    doc = Document(user_id=user.id, filename="paper.txt", label="public", sha256="x")
    db.add(doc)
    db.flush()
    chunks = [DocumentChunk(document_id=doc.id, idx=i, page=i + 1, text=t) for i, t in enumerate(texts)]
    db.add_all(chunks)
    db.commit()
    return doc, chunks


def test_follow_up_retrieves_with_the_earlier_question(db):
    set_policy(db, retrieval_top_k=1)
    doc, _ = _add_doc(db, [
        "Batch normalization rescales activations across a mini batch.",
        "Dropout randomly zeroes hidden units so the network cannot rely on single neurons.",
    ])
    history = convo("How does dropout work?", "It zeroes random hidden units.")
    plan, _ = run(db, history + [{"role": "user", "content": "Why does that help?"}], document_ids=[doc.id])
    assert plan.follow_up and plan.draft.evidence[0].page == 2
    # Without the history the same words find nothing and fall back to the first page.
    plan, _ = run(db, [{"role": "user", "content": "Why does that help?"}], document_ids=[doc.id])
    assert not plan.follow_up and plan.draft.evidence[0].page == 1


def test_evidence_carry_over_keeps_previous_passages_for_follow_ups(db):
    set_policy(db, retrieval_top_k=1)
    doc, chunks = _add_doc(db, ["Results on SQuAD improve by two points.", "The model uses twelve layers."])
    history = convo("What did they find?", "Scores improved.")
    plan, _ = run(db, history + [{"role": "user", "content": "Tell me more"}],
                  document_ids=[doc.id], prior_chunk_ids=[chunks[1].id])
    assert plan.draft.evidence[0].chunk_id == chunks[1].id


def test_follow_up_inherits_the_previous_task(db):
    plan, _ = run(db, convo("Summarise the attention section", "It explains attention.", "Make it shorter"))
    assert plan.task == "summary"
    plan, _ = run(db, convo("Summarise the attention section", "It explains attention.", "What is BERT?"))
    assert plan.task == "explain"


def test_follow_up_after_a_hard_question_is_routed_as_hard(db):
    hard = ("Compare the two training methods, analyze their trade-offs step by step, "
            "and justify which one is more robust?")
    plan, outcome = run(db, convo(hard, "Method A is more robust.", "Why?"))
    assert plan.follow_up and plan.info.complexity >= 0.6 and outcome.model == "mock-strong"
    assert plan.x[ctx_feature_index("follow_up")] == 1.0


def ctx_feature_index(name: str) -> int:
    from app.core.features import FeatureExtractor

    return FeatureExtractor().names().index(name)


# ------------------------------------------------------------ history window


def long_conversation(exchanges: int, words: int = 120) -> list[dict]:
    turns = []
    for i in range(exchanges):
        turns += [f"Question {i} about topic{i} " + "detail " * words, f"Answer {i} " + "content " * words]
    return convo(*turns)


def test_split_history_keeps_whole_recent_exchanges():
    history = long_conversation(10)
    older, recent = ctx.split_history(history, budget_tokens=1000)
    assert older and recent and older + recent == history
    assert recent[0]["role"] == "user"
    assert ctx.split_history(history[:2], budget_tokens=1000) == ([], history[:2])


def test_short_conversations_are_sent_verbatim(db):
    history = convo("What is dropout?", "A regulariser.")
    plan, outcome = run(db, history + [{"role": "user", "content": "Why?"}])
    assert outcome.history_mode == "full" and outcome.history_sent == 2 and not plan.draft.omitted


def test_relevant_older_turns_are_kept_until_a_summary_exists(db):
    # One exchange is about 520 tokens: 1200 leaves room for the last exchange
    # verbatim plus exactly one relevant older exchange.
    set_policy(db, history_budget_tokens=1200, history_summary_enabled=False)
    history = long_conversation(10)
    plan, outcome = run(db, history + [{"role": "user", "content": "Go back to topic2 please"}])
    assert outcome.history_mode == "relevant_turns" and plan.draft.omitted
    sent = " ".join(m["content"] for m in plan.draft.history)
    assert "topic2" in sent and "topic0 " not in sent
    assert any("left out" in n for n in plan.notices)


def test_summary_is_written_locally_in_the_background_and_used_next_turn(db):
    set_policy(db, history_budget_tokens=1000)
    history = long_conversation(10)
    question = {"role": "user", "content": "And the last point?"}
    plan, first = run(db, history + [question])
    assert first.status == "ok" and first.history_mode == "relevant_turns"
    attempt = db.execute(select(Attempt).where(Attempt.purpose == "summary")).scalars().one()
    assert attempt.model_name == "mock-local" and attempt.status == "ok" and attempt.cost_usd == 0
    assert all(d["model"] != "mock-local" for d in MockProvider.dispatched)  # local calls are not recorded

    nxt = history + [question, {"role": "assistant", "content": first.text}, {"role": "user", "content": "Thanks, why?"}]
    plan, second = run(db, nxt)
    assert second.history_mode == "summary" and plan.draft.memory
    system = plan.draft.render()[0]["content"]
    assert ctx.MEMORY_HEADER in system and plan.draft.memory in system


def test_summarizer_refuses_cloud_models():
    spec = ModelSpec("cloud", "anthropic", "x", "strong", False, None, 1000, 100, 1, 1, {}, 1.0)
    try:
        ctx.summarizer.schedule(user_id="u", conversation=long_conversation(10), spec=spec, budget_tokens=500, ttl_s=60)
    except ValueError:
        return
    raise AssertionError("a cloud model was accepted for summaries")


def test_identifier_in_an_omitted_turn_still_blocks_cloud(db):
    set_policy(db, history_budget_tokens=600, history_summary_enabled=False)
    history = convo(f"My CNIC is {CNIC}, remember it.", "Noted.") + long_conversation(6)
    hard = "Compare both methods, analyze the trade-offs step by step and justify which is more robust?"
    plan, outcome = run(db, history + [{"role": "user", "content": hard}])
    assert all(CNIC not in m["content"] for m in plan.draft.history)  # not sent ...
    assert outcome.sensitive and outcome.model == "mock-local"  # ... but still counts
    assert MockProvider.dispatched == []


# ---------------------------------------------------------- prompt caching


def test_cache_aware_cost_and_claude_prompt_caching_flag():
    claude = ModelSpec("c", "anthropic", "m", "strong", False, None, 1000, 100, 4.0, 20.0, {}, 1.0)
    full = claude.cost_usd(10_000, 0)
    cached = claude.cost_usd(10_000, 0, cache_read=8_000)
    assert full == 0.04 and round(cached, 6) == round((2_000 + 800) * 4.0 / 1e6, 6)
    other = ModelSpec("o", "openai", "m", "strong", False, None, 1000, 100, 4.0, 20.0, {}, 1.0)
    assert other.cost_usd(10_000, 0, cache_read=8_000) == full  # no discount assumed unless configured
    req = ChatRequest(model_id="m", messages=[], max_tokens=10)
    assert build_kwargs(req, "sys", [])["cache_control"] == {"type": "ephemeral"}
    off = ChatRequest(model_id="m", messages=[], max_tokens=10, params={"prompt_caching": False})
    assert "cache_control" not in build_kwargs(off, "sys", [])
