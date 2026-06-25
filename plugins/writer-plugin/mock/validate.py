#!/usr/bin/env python3
"""Mock artifact 格式校验脚本 —— 对照 v5 设计文档的数据结构"""

import json
import re
import sys
from pathlib import Path

BASE = Path("/Users/sunyifan1/Desktop/writer_mock_artifacts")

errors = []
warnings = []

def err(msg): errors.append(msg)
def warn(msg): warnings.append(msg)

# ── 加载文件 ──────────────────────────────────────────────

try:
    outline         = json.loads((BASE / "mock_outline.json").read_text())
    draft_section_1 = json.loads((BASE / "mock_draft_section_1.json").read_text())
    draft_section_2 = json.loads((BASE / "mock_draft_section_2.json").read_text())
    review_report   = json.loads((BASE / "mock_review_report.json").read_text())
    draft_md        = (BASE / "mock_draft_document.md").read_text()
    output_md       = (BASE / "mock_writing_output.md").read_text()
    revised_md      = (BASE / "mock_revised_document.md").read_text()
except FileNotFoundError as e:
    print(f"[FATAL] 文件缺失: {e}")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"[FATAL] JSON 解析失败: {e}")
    sys.exit(1)


# ── 1. mock_outline.json ──────────────────────────────────

print("=== 1. mock_outline.json ===")

out_data = outline.get("data", {})
if outline.get("schema") != "lazyllm.writer.WritingOutline":
    err("outline schema 应为 lazylm.writer.WritingOutline")

if not out_data.get("outline_id"):
    err("outline 缺少 outline_id")
if not out_data.get("title"):
    err("outline 缺少 title")
elif out_data["title"] != "星辰大帝":
    warn(f"outline title 不匹配: {out_data['title']}")

nodes = out_data.get("nodes", [])
if not nodes:
    err("outline.nodes 为空")

node_ids = set()
for node in nodes:
    nid = node.get("node_id")
    if not nid:
        err("OutlineNode 缺少 node_id")
    elif nid in node_ids:
        err(f"OutlineNode.node_id 重复: {nid}")
    else:
        node_ids.add(nid)

    for field in ["title", "level", "instruction"]:
        if field not in node:
            warn(f"OutlineNode [{nid}] 缺少字段: {field}")
    if "constraints" not in node:
        warn(f"OutlineNode [{nid}] 缺少 constraints")

print(f"  outline_id: {out_data.get('outline_id')}")
print(f"  title: {out_data.get('title')}")
print(f"  nodes: {len(nodes)} (楔子 + 12章)")
print(f"  node_ids: {sorted(node_ids)}")


# ── 2. mock_draft_section_1/2.json ────────────────────────

print("\n=== 2. mock_draft_section_1.json + _2.json ===")

all_section_ids = set()
all_block_ids = set()
all_instruction_ids = set()
all_outline_node_refs = set()

for label, bundle_json in [("section_1", draft_section_1), ("section_2", draft_section_2)]:
    print(f"\n--- {label} ---")

    if bundle_json.get("schema") != "lazyllm.writer.SectionDraftBundle":
        err(f"{label} schema 应为 lazylm.writer.SectionDraftBundle")

    data = bundle_json.get("data", {})
    if not data.get("bundle_id"):
        err(f"{label} 缺少 bundle_id")
    if data.get("title") != "星辰大帝":
        warn(f"{label} title 不匹配")

    sections = data.get("sections", [])
    if not sections:
        err(f"{label}.sections 为空")

    print(f"  bundle_id: {data.get('bundle_id')}")
    print(f"  sections: {len(sections)}")

    for sec in sections:
        onid = sec.get("outline_node_id", "?")
        all_outline_node_refs.add(onid)

        # ── instruction 校验 ──
        ins = sec.get("instruction", {})
        iid = ins.get("instruction_id", "?")
        if not ins:
            err(f"  [{onid}] 缺少 instruction")

        for field in ["instruction_id", "section_title", "section_goal", "required_points",
                       "fact_constraints", "style_constraints", "relation_constraints",
                       "visual_needs", "expected_blocks"]:
            if field not in ins:
                err(f"  [{onid}] instruction 缺少字段: {field}")

        if iid in all_instruction_ids:
            err(f"  [{onid}] instruction_id 重复: {iid}")
        else:
            all_instruction_ids.add(iid)

        # ── draft 校验 ──
        draft = sec.get("draft", {})
        if not draft:
            err(f"  [{onid}] 缺少 draft")

        sid = draft.get("section_id", "?")
        if sid in all_section_ids:
            err(f"  [{onid}] section_id 重复: {sid}")
        else:
            all_section_ids.add(sid)

        for field in ["section_id", "title", "blocks"]:
            if field not in draft:
                err(f"  [{onid}] draft 缺少字段: {field}")

        blocks = draft.get("blocks", [])
        if not blocks:
            err(f"  [{onid}] draft.blocks 为空")

        # 检查 expected_blocks 数量和实际 blocks 数量
        expected = ins.get("expected_blocks", [])
        if expected and abs(len(expected) - len(blocks)) > 2:
            warn(f"  [{onid}] expected_blocks={len(expected)} vs draft.blocks={len(blocks)} 差值 > 2")

        for blk in blocks:
            bid = blk.get("block_id", "?")
            if bid in all_block_ids:
                err(f"  [{onid}] block_id 重复: {bid}")
            else:
                all_block_ids.add(bid)

            for field in ["block_id", "heading", "content", "subtasks", "status"]:
                if field not in blk:
                    err(f"  [{onid}/{bid}] DraftBlock 缺少字段: {field}")

            if not blk.get("content", "").strip():
                warn(f"  [{onid}/{bid}] content 为空")

            status = blk.get("status")
            if status not in ("drafted", "edited", "failed"):
                warn(f"  [{onid}/{bid}] status 值异常: {status}")

        # 检查 subtasks
        subtasks = draft.get("subtasks", [])
        for st in subtasks:
            for field in ["subtask_id", "subtask_type", "description", "placeholder", "blocking", "status"]:
                if field not in st:
                    err(f"  [{onid}] WritingSubTask 缺少字段: {field}")

        # 简要输出
        ins_title = ins.get("section_title", "?")
        print(f"  [{onid}] {ins_title}")
        print(f"    instruction_id={iid}, section_id={sid}, blocks={len(blocks)}, subtasks={len(subtasks)}")

# 交叉校验：outline_node_id 必须在 outline 中存在
print(f"\n--- 交叉校验 ---")
for ref in sorted(all_outline_node_refs):
    if ref not in node_ids:
        err(f"draft 引用的 outline_node_id [{ref}] 在 outline 中不存在")


# ── 3. mock_review_report.json ─────────────────────────────

print("\n=== 3. mock_review_report.json ===")

rev_data = review_report.get("data", {})
if review_report.get("schema") != "lazyllm.writer.AuditResult":
    err("review_report schema 应为 lazylm.writer.AuditResult")

for field in ["is_passed", "score", "summary", "issues"]:
    if field not in rev_data:
        err(f"review_report 缺少字段: {field}")

score = rev_data.get("score")
if not isinstance(score, int) or not (0 <= score <= 100):
    err(f"score 应在 0-100 之间: {score}")

issues = rev_data.get("issues", [])
valid_severities = {"high", "medium", "low"}
valid_categories = {"format", "coverage", "relevance", "evidence", "style"}

print(f"  is_passed: {rev_data.get('is_passed')}")
print(f"  score: {score}")
print(f"  issues: {len(issues)}")

for iss in issues:
    sev = iss.get("severity")
    cat = iss.get("category")
    loc = iss.get("location", "?")

    for field in ["severity", "category", "location", "description", "suggestion"]:
        if field not in iss:
            err(f"AuditIssue 缺少字段: {field}")

    if sev not in valid_severities:
        err(f"issue severity 无效: {sev}")
    if cat not in valid_categories:
        err(f"issue category 无效: {cat}")
    if not iss.get("description"):
        warn(f"issue description 为空")

    print(f"  [{sev}/{cat}] {loc}: {iss.get('description', '')[:60]}...")

# 交叉校验：location 引用的 section 存在
md_section_names = set(re.findall(r'^##\s+(.+)$', draft_md, re.MULTILINE))
for iss in issues:
    loc = iss.get("location", "")
    # 提取 sec-xxx 引用
    sec_refs = re.findall(r'sec-\w+', loc)
    for sref in sec_refs:
        if sref not in all_section_ids:
            warn(f"review issue location 引用不存在的 section: {sref}, 已知: {sorted(all_section_ids)}")


# ── 4. Markdown 文件 ──────────────────────────────────────

print("\n=== 4. Markdown 文件 ===")

for label, content in [("draft_document", draft_md), ("writing_output", output_md), ("revised_document", revised_md)]:
    if not content.strip():
        err(f"{label}.md 为空")

    # 检查标题
    if not content.startswith("# 星辰大帝"):
        warn(f"{label}.md 标题不是 '星辰大帝'")

    # 提取所有 ## 标题
    headings = re.findall(r'^##\s+(.+)$', content, re.MULTILINE)
    print(f"  {label}.md: {len(content)} 字符, {len(headings)} 个二级标题")
    if len(headings) < 13:
        warn(f"{label}.md 标题数 {len(headings)} < 13（楔子+12章）")


# ── 5. 完整性检查 ──────────────────────────────────────────

print("\n=== 5. 完整性检查 ===")

expected_sections = [
    "sec-prologue", "sec-ch01", "sec-ch02", "sec-ch03", "sec-ch04",
    "sec-ch05", "sec-ch06", "sec-ch07", "sec-ch08", "sec-ch09",
    "sec-ch10", "sec-ch11", "sec-ch12",
]
for es in expected_sections:
    if es not in all_section_ids:
        err(f"缺少 section: {es}")

# 检查 section_1 和 section_2 的拆分点
s1_ids = {sec["draft"]["section_id"] for sec in draft_section_1["data"]["sections"]}
s2_ids = {sec["draft"]["section_id"] for sec in draft_section_2["data"]["sections"]}
overlap = s1_ids & s2_ids
if overlap:
    err(f"section_1 和 section_2 有重叠: {overlap}")
print(f"  section_1 覆盖: {sorted(s1_ids)}")
print(f"  section_2 覆盖: {sorted(s2_ids)}")


# ── 输出结果 ───────────────────────────────────────────────

print(f"\n{'='*60}")
print(f"校验完成: {len(errors)} 个错误, {len(warnings)} 个警告")
print(f"{'='*60}")

if errors:
    print("\n[错误]")
    for e in errors:
        print(f"  ❌ {e}")

if warnings:
    print("\n[警告]")
    for w in warnings:
        print(f"  ⚠️  {w}")

if not errors and not warnings:
    print("\n✅ 全部通过！")

sys.exit(1 if errors else 0)
