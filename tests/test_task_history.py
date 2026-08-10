from pathlib import Path

from experimental.qml_v4.backend.task_history import (
    TranslationTaskHistoryStore,
    build_subtask_records,
    make_task_id,
    normalize_failed_blocks,
    sanitize_config,
)


def test_task_history_store_upsert_list_and_clear(tmp_path: Path):
    store = TranslationTaskHistoryStore(path=tmp_path / "history.json", limit=5)

    task_id = make_task_id()
    record = store.upsert(
        task_id,
        {
            "status": "running",
            "input_path": "in.epub",
            "output_path": "out.epub",
            "api_key": "secret",
            "provider": "hymt2",
        },
    )
    assert record["task_id"] == task_id
    assert record["status"] == "running"
    assert "api_key" not in record

    updated = store.upsert(task_id, {"status": "completed", "progress": 1.0})
    assert updated["status"] == "completed"
    assert updated["progress"] == 1.0

    second_id = make_task_id()
    store.upsert(second_id, {"status": "failed"})

    latest = store.latest()
    assert latest["task_id"] == second_id
    assert latest["status"] == "failed"

    recent = store.list_recent(2)
    assert [item["task_id"] for item in recent] == [second_id, task_id]

    removed = store.clear()
    assert removed == 2
    assert store.load() == []


def test_sanitize_config_removes_secrets():
    payload = sanitize_config(
        {
            "inp": "a.epub",
            "out": "b.epub",
            "api_key": "secret",
            "proofread_api_key": "secret-2",
            "batch_size": 4,
            "non_scalar": {"nested": True},
        }
    )
    assert payload["api_key"] == ""
    assert payload["proofread_api_key"] == ""
    assert payload["batch_size"] == 4
    assert "non_scalar" not in payload


def test_normalize_failed_blocks_keeps_actionable_fields():
    blocks = normalize_failed_blocks(
        failed_details=[
            {"text": "旅ゆけば", "reason": "未返回安全译文"},
            {"text": "旅ゆけば", "reason": "duplicate"},
        ],
        residue_details=[
            {
                "original": "猿とな",
                "translated": "猿とな",
                "fragments": ["とな"],
                "reason": "译文疑似仍有日文残留",
            }
        ],
        residue_samples=[
            "fragment: チロリ / お | text: 回来的妻子，手里拿着チロリ。"
        ],
    )

    assert len(blocks) == 3
    assert blocks[0]["kind"] == "failed"
    assert blocks[0]["text"] == "旅ゆけば"
    assert blocks[1]["kind"] == "residue"
    assert blocks[1]["translation"] == "猿とな"
    assert blocks[1]["fragments"] == ["とな"]
    assert blocks[2]["kind"] == "save_residue"
    assert blocks[2]["fragments"] == ["チロリ", "お"]
    assert blocks[2]["text"] == "回来的妻子，手里拿着チロリ。"


def test_subtask_records_persist_progress_and_resume_state(tmp_path: Path):
    store = TranslationTaskHistoryStore(path=tmp_path / "history.json", limit=5)
    task_id = make_task_id()
    texts = ["吾輩は猫である。", "名前はまだ無い。", "吾輩は猫である。"]

    store.upsert(task_id, {"status": "running", "input_path": "book.epub"})
    initialized = store.initialize_subtasks(task_id, texts)

    assert initialized["total_texts"] == 3
    assert initialized["completed_texts"] == 0
    assert initialized["subtasks"][0]["index"] == 0
    assert initialized["subtasks"][0]["status"] == "pending"
    assert build_subtask_records(["abc"])[0]["chars"] == 3

    result = store.mark_subtask_success(task_id, "吾輩は猫である。", "我是猫。")
    record = result["record"]
    assert result["changed"] == 2
    assert record["completed_texts"] == 2
    assert record["progress"] == 0.6667
    assert record["subtasks"][0]["translation"] == "我是猫。"
    assert record["subtasks"][2]["translation"] == "我是猫。"

    resumed = store.initialize_subtasks(task_id, texts, preserve_existing=True)
    assert resumed["completed_texts"] == 2
    assert resumed["subtasks"][0]["status"] == "success"
    assert resumed["subtasks"][1]["status"] == "pending"

    unfinished = store.latest_unfinished()
    assert unfinished["task_id"] == task_id


def test_mark_subtasks_problem_updates_matching_blocks(tmp_path: Path):
    store = TranslationTaskHistoryStore(path=tmp_path / "history.json", limit=5)
    task_id = make_task_id()
    store.upsert(task_id, {"status": "failed"})
    store.initialize_subtasks(task_id, ["旅ゆけば", "翻译完成"])

    result = store.mark_subtasks_problem(
        task_id,
        [{"kind": "failed", "text": "旅ゆけば", "reason": "未返回安全译文"}],
    )

    assert result["changed"] == 1
    record = store.latest()
    assert record["failed_texts"] == 1
    assert record["subtasks"][0]["status"] == "failed"
    assert record["subtasks"][0]["reason"] == "未返回安全译文"

def test_mark_blocks_success_clears_failed_blocks(tmp_path: Path):
    store = TranslationTaskHistoryStore(path=tmp_path / "history.json", limit=5)
    task_id = make_task_id()
    source = "source failed text"
    store.upsert(task_id, {"status": "failed"})
    store.initialize_subtasks(task_id, [source, "already ok"])
    store.mark_subtasks_problem(
        task_id,
        [{"kind": "failed", "text": source, "reason": "no safe translation"}],
    )
    store.upsert(task_id, {"failed_blocks": [{"kind": "failed", "text": source, "reason": "no safe translation"}]})

    result = store.mark_blocks_success(task_id, {source: "fixed translation"})
    record = result["record"]

    assert result["changed"] == 1
    assert result["remaining_blocks"] == 0
    assert record["failed_blocks"] == []
    assert record["subtasks"][0]["status"] == "success"
    assert record["subtasks"][0]["translation"] == "fixed translation"


def test_record_recovery_results_persists_attempt_metadata(tmp_path: Path):
    store = TranslationTaskHistoryStore(path=tmp_path / "history.json", limit=5)
    task_id = make_task_id()
    source = "failed source"
    store.upsert(task_id, {"status": "failed"})
    store.initialize_subtasks(task_id, [source])
    store.upsert(
        task_id,
        {"failed_blocks": [{"kind": "failed", "text": source, "reason": "empty"}]},
    )

    result = store.record_recovery_results(
        task_id,
        {
            source: {
                "attempts": 2,
                "action": "RETRANSLATE",
                "status": "needs_review",
                "reason": "still incomplete",
            }
        },
    )
    record = result["record"]

    assert result["changed"] == 2
    assert record["failed_blocks"][0]["recovery_attempts"] == 2
    assert record["failed_blocks"][0]["recovery_status"] == "needs_review"
    assert record["subtasks"][0]["recovery_action"] == "RETRANSLATE"


def test_latest_unfinished_ignores_cancelled_tasks(tmp_path: Path):
    store = TranslationTaskHistoryStore(path=tmp_path / "history.json", limit=5)
    cancelled_id = make_task_id()
    store.upsert(cancelled_id, {"status": "cancelled"})
    failed_id = make_task_id()
    store.upsert(failed_id, {"status": "failed"})

    assert store.latest_unfinished()["task_id"] == failed_id

    store.upsert(failed_id, {"status": "completed"})
    assert store.latest_unfinished() == {}


def test_list_recent_returns_subtask_summary_only(tmp_path: Path):
    store = TranslationTaskHistoryStore(path=tmp_path / "history.json", limit=5)
    task_id = make_task_id()
    store.upsert(task_id, {"status": "running"})
    store.initialize_subtasks(task_id, ["a", "b"])

    row = store.list_recent(1)[0]
    assert "subtasks" not in row
    assert row["subtask_count"] == 2
    assert row["total_texts"] == 2


def test_terminal_tasks_drop_subtask_payload_but_keep_summary(tmp_path: Path):
    path = tmp_path / "history.json"
    store = TranslationTaskHistoryStore(path=path, limit=5)
    task_id = make_task_id()
    store.upsert(task_id, {"status": "running"})
    store.initialize_subtasks(task_id, ["原文一", "原文二"])
    store.mark_subtask_success(task_id, "原文一", "译文一")

    store.upsert(task_id, {"status": "completed"})
    record = store.latest()

    assert record["status"] == "completed"
    assert "subtasks" not in record
    assert record["subtask_count"] == 2
    assert store.list_recent(1)[0]["subtask_count"] == 2
    assert "译文一" not in path.read_text(encoding="utf-8")


def test_recoverable_tasks_keep_subtasks_for_resume(tmp_path: Path):
    store = TranslationTaskHistoryStore(path=tmp_path / "history.json", limit=5)
    task_id = make_task_id()
    store.upsert(task_id, {"status": "running"})
    store.initialize_subtasks(task_id, ["原文"])
    store.mark_subtask_success(task_id, "原文", "译文")
    store.upsert(task_id, {"status": "paused"})

    record = store.latest()
    assert record["subtasks"][0]["translation"] == "译文"
    assert store.latest_unfinished()["task_id"] == task_id
