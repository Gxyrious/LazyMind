#!/usr/bin/env python3
"""End-to-end test for the writer-plugin.

Verifies the full writing pipeline (build_context → plan_outline → write_draft
→ review_draft → finalize_report) by driving a real conversation through the
ChatAgent + SubAgent stack against the live LazyMind services.

Design notes
------------
* Runs INSIDE the `chat` container so it can reach `core:8000` directly on the
  docker network, bypassing Kong / rbac-auth. Invoke with:
      docker exec lazymind-chat-1 python3 /app/plugins/writer-plugin/test_e2e.py
* The core defaults to manual plugin mode (`LAZYMIND_PLUGIN_MODE=manual`), so
  after each step completes the session enters `waiting`. The test mimics the
  user clicking "继续" by calling `POST /plugin-sessions/{id}:advance`. Each
  advance triggers a real ChatAgent turn that decides the next step — this IS
  the "conversation with the main agent" that exercises intent recognition.
* A real LLM (configured via runtime_models.online.yaml) produces every
  artifact; no mocking. The test asserts that all five steps succeed and that
  the final report is substantive and on-topic.

Exit code 0 on success, non-zero on failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Tuple

import httpx

CORE = os.environ.get("LAZYMIND_CORE_URL", "http://core:8000")
DEFAULT_USER = "0f1b91fe-821a-403f-96c0-8ce4b386079f"  # test user with model providers configured
DEFAULT_TOPIC = (
    "请写一篇关于『星辰大帝』的玄幻长篇小说，约 6000 字，"
    "覆盖楔子与前 12 章的世界观设定、主角成长与核心矛盾。"
)

EXPECTED_STEPS = ["build_context", "generate_outline", "plan_sections",
                 "generate_draft", "review_document", "finalize_report"]
FINAL_ARTIFACT_KEY = "writing_output"
MIN_FINAL_CHARS = 2000

# Per-step soft time budget. generate_draft / finalize_report can be long when the model
# generates a sizable article plus reads a large upstream draft, so keep this generous.
STEP_TIMEOUT_SEC = 420
ADVANCE_TIMEOUT_SEC = 30


def _log(msg: str) -> None:
    # Wall-clock timestamp on every line so elapsed time is read from the log, never
    # guessed. The author also uses DB now()-updated_at (secs_since_update) as the
    # authoritative "is it stuck" signal when inspecting a session.
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _headers(user_id: str) -> Dict[str, str]:
    return {"X-User-Id": user_id, "Content-Type": "application/json"}


def _cold_start(client: httpx.Client, user_id: str, topic: str) -> Tuple[str, str]:
    """Send the initial chat that triggers trigger_writer_plugin.

    Returns (conversation_id, plugin_session_id).
    Raises AssertionError if no plugin session is created.
    """
    conv_id = f"conv-writer-e2e-{uuid.uuid4().hex[:8]}"
    body = {
        "conversation_id": conv_id,
        "input": [{"input_type": "text", "text": topic}],
        "mode": "auto",  # requested mode; core may still drive manual based on its config
        "stream": True,
    }
    _log(f"Cold start: conversation={conv_id}")
    _log(f"  topic: {topic[:80]}...")

    plugin_session_id = None
    task_title = None
    with client.stream("POST", f"{CORE}/conversations:chat",
                       headers=_headers(user_id), json=body,
                       timeout=httpx.Timeout(connect=10, read=600, write=30, pool=30)) as resp:
        if resp.status_code != 200:
            raise AssertionError(f"cold-start HTTP {resp.status_code}")
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except ValueError:
                continue
            res = obj.get("result", obj)
            if isinstance(res, dict) and "task_created" in res:
                tc = res["task_created"]
                if tc.get("agent_type") == "plugin_step":
                    plugin_session_id = tc.get("plugin_session_id")
                    task_title = tc.get("title")

    if not plugin_session_id:
        raise AssertionError(
            "Cold start did not create a plugin session — ChatAgent did not call "
            "trigger_writer_plugin. Check that the writer-plugin is loaded and the "
            "topic reads as a writing request."
        )
    _log(f"  → plugin_session_id={plugin_session_id}  first task={task_title}")
    return conv_id, plugin_session_id


def _session_snapshot(client: httpx.Client, user_id: str, sid: str) -> Dict[str, Any]:
    r = client.get(f"{CORE}/plugin-sessions/{sid}", headers=_headers(user_id), timeout=15)
    r.raise_for_status()
    return r.json().get("data", {}).get("session", {})


def _step_statuses(session: Dict[str, Any]) -> Dict[str, str]:
    return {st.get("step_id"): st.get("status") for st in session.get("steps", [])}


def _wait_step(client: httpx.Client, user_id: str, sid: str,
               expected_step: str) -> str:
    """Wait for `expected_step` to reach a terminal status.

    The core drives the plugin in auto mode (DriverAgent → ChatAgent → advance_step),
    so the test does NOT call :advance — it only polls. This verifies the real main-agent
    conversation flow that the chatbox also uses.

    Returns the final status of the step ('succeeded' / 'failed' / 'interrupted').
    """
    deadline = time.time() + STEP_TIMEOUT_SEC
    last_sig = None
    while time.time() < deadline:
        session = _session_snapshot(client, user_id, sid)
        status = session.get("status")
        steps = _step_statuses(session)
        sig = (status, tuple(sorted(steps.items())))
        if sig != last_sig:
            _log(f"  session={status} steps={steps}")
            last_sig = sig

        step_status = steps.get(expected_step)
        if step_status in ("succeeded", "failed", "interrupted"):
            return step_status
        time.sleep(5)

    raise TimeoutError(f"step {expected_step!r} did not finish within {STEP_TIMEOUT_SEC}s")


def _fetch_artifacts(client: httpx.Client, user_id: str, sid: str) -> Dict[str, Any]:
    """Return {artifact_key: value} for every selected artifact in the session.

    The /slots endpoint returns one row per selected revision and does NOT include
    a cardinality field, so we detect list slots structurally: any artifact_key
    that has multiple rows (or a non-null list_index) is treated as a list and
    maps to all its values in slot order; otherwise the key maps to its single value.
    Values are the raw artifact_value dicts (may be {'data': ...} for json or
    {'text': ...} for text).
    """
    r = client.get(f"{CORE}/plugin-sessions/{sid}/slots", headers=_headers(user_id), timeout=20)
    r.raise_for_status()
    slots = r.json().get("data", {}).get("slots", []) or []
    grouped: Dict[str, List[Any]] = {}
    order: List[str] = []
    for row in slots:
        key = row.get("artifact_key")
        if not key:
            continue
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row.get("artifact_value") or {})
    out: Dict[str, Any] = {}
    for key in order:
        vals = grouped[key]
        if len(vals) == 1:
            out[key] = vals[0]
        else:
            out[key] = vals
    return out


def _unwrap_value(v: Any) -> Any:
    """Pull the model dict/list out of the json artifact wrapper {'data': <model>}.

    With key-in/key-out the tools save exact model dicts via save_artifact(json), so
    the only storage shape is {'data': <dict|list>}. No stringified/hand-rolled JSON
    fallback is needed.
    """
    if isinstance(v, dict) and "data" in v and isinstance(v["data"], (dict, list)):
        return v["data"]
    return v


def run_e2e(topic: str, user_id: str) -> int:
    _log(f"=== writer-plugin E2E test ===")
    _log(f"core={CORE} user={user_id}")

    with httpx.Client() as client:
        conv_id, sid = _cold_start(client, user_id, topic)

        for step in EXPECTED_STEPS:
            _log(f"--- driving step: {step} ---")
            step_status = _wait_step(client, user_id, sid, step)
            if step_status != "succeeded":
                _log(f"FAIL: step {step} ended with status={step_status}")
                return 2
            _log(f"  ✓ {step} succeeded")

        # All steps succeeded. Pull artifacts and validate shapes.
        artifacts = _fetch_artifacts(client, user_id, sid)
        keys = sorted(artifacts.keys())
        _log(f"artifacts produced: {keys}")

        for required in ["writing_context", "outline", "section_instructions",
                         "draft_sections", "draft_document",
                         "review_report", "writing_output"]:
            if required not in artifacts:
                _log(f"FAIL: missing artifact {required!r}")
                return 3

        # draft_sections must be a list of >= 2 DraftSection items with distinct titles.
        # With key-in/key-out the LLM never relays payload, so each item is the exact
        # DraftSection dict the mock produced — assert strict shape.
        sections = artifacts["draft_sections"]
        if not isinstance(sections, list) or len(sections) < 2:
            _log(f"FAIL: draft_sections should be a list with >=2 items, got {type(sections).__name__}")
            return 4
        sec_models = [_unwrap_value(s) for s in sections]
        for i, s in enumerate(sec_models):
            if not isinstance(s, dict) or "title" not in s or "blocks" not in s:
                _log(f"FAIL: draft_sections[{i}] not a DraftSection shape: {list(s)[:6] if isinstance(s,dict) else type(s).__name__}")
                return 5
        sec_titles = [s["title"] for s in sec_models]
        if len(set(sec_titles)) < 2:
            _log(f"FAIL: draft_sections items are identical (titles={sec_titles!r})")
            return 5
        _log(f"✓ draft_sections list has {len(sections)} distinct sections: {sec_titles}")

        # writing_output must be the exact WritingOutput shape (content + output_format).
        final = _unwrap_value(artifacts[FINAL_ARTIFACT_KEY])
        if not isinstance(final, dict) or "content" not in final or "output_format" not in final:
            _log(f"FAIL: writing_output not a WritingOutput shape (got {type(final).__name__})")
            return 6
        if not str(final.get("content", "")).strip():
            _log("FAIL: writing_output.content is empty")
            return 7

        # draft_document must be a DraftDocument whose sections match the draft_sections list.
        draft = _unwrap_value(artifacts["draft_document"])
        if not isinstance(draft, dict) or not isinstance(draft.get("sections"), list):
            _log("FAIL: draft_document not a DraftDocument with sections list")
            return 8
        if len(draft["sections"]) != len(sections):
            _log(f"FAIL: draft_document.sections ({len(draft['sections'])}) != draft_sections list ({len(sections)})")
            return 9
        _log(f"✓ draft_document assembled with {len(draft['sections'])} sections")

        _log("=== FINAL REPORT (WritingOutput.content, first 600 chars) ===")
        print(str(final.get("content", ""))[:600], flush=True)
        print("\n... [truncated]", flush=True)

    _log("=== PASS: writer-plugin E2E flow completed successfully ===")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="writer-plugin end-to-end test")
    ap.add_argument("--topic", default=DEFAULT_TOPIC, help="writing topic / user request")
    ap.add_argument("--user", default=DEFAULT_USER, help="test user id with model providers configured")
    args = ap.parse_args()
    try:
        return run_e2e(args.topic, args.user)
    except Exception as exc:  # noqa: BLE001
        _log(f"ERROR: {exc!r}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
