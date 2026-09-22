#!/usr/bin/env python3
"""用真正的報告重建 corpus 與 reports/。

為什麼需要：Layer 1 上線後的頭一批資料是拿 `last_assistant_message` 當產出去評的，
那不是報告，是收尾句（見 transcript.py 的說明）。那批分數不能用，但 subagent
transcript 多半還在磁碟上，報告抽得回來，所以可以重評而不用重跑任務。

重建的方式是**合成一份 SubagentStop payload 餵給那兩支 hook**，不是在這裡再實作
一次萃取、呼叫 Jev 與門檻判定。整條路徑只有一份實作，重建出來的列就跟之後線上
寫的列同構；否則這支腳本自己會變成第二個漂移來源。

用法：
    backfill_corpus.py                 # 只報告：有多少列可重建、多少列沒救
    backfill_corpus.py --apply         # 重建並換檔（原檔備份成 .bak-<時間>）
    backfill_corpus.py --limit 5 --apply

重評會實際呼叫 Jev（每筆約 $0.00008），所以需要 TYPESAFE_API_KEY，
由 hook 自己從 ~/.config/claude/typesafe.env 讀。
"""
import argparse
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
EVAL_DIR = os.environ.get("EVAL_DIR", os.path.join(HOME, ".local/share/model-router-eval"))
PROJECTS = os.environ.get("CLAUDE_PROJECTS", os.path.join(HOME, ".claude/projects"))
JUDGE_HOOK = os.path.join(HOME, ".config/claude/hooks/judge-subagent-output.sh")
ARCHIVE_HOOK = os.path.join(HOME, ".config/claude/hooks/archive-subagent-report.sh")


def find_transcript(agent_id, projects_root):
    """agent_id -> subagent transcript 路徑；找不到回 None。

    檔名是 `agent-<agent_id>.jsonl`，比對完整檔名而不是前綴，否則 id 互為前綴時會配錯。
    """
    hits = glob.glob(os.path.join(
        projects_root, "*", "*", "subagents", "agent-%s.jsonl" % agent_id))
    return hits[0] if hits else None


def build_payload(row, transcript_path, last_assistant_message):
    """合成 SubagentStop 事件，形狀比照 Claude Code 真的送進 hook 的那份。"""
    return {
        "agent_id": row.get("agent_id") or "",
        "agent_type": row.get("agent_type") or "",
        "session_id": row.get("session_id") or "",
        "cwd": row.get("cwd") or "",
        "agent_transcript_path": transcript_path,
        "last_assistant_message": last_assistant_message or "",
    }


def _read_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _old_last_message(agent_id, reports_dir):
    """存檔裡的舊 `report` 就是當初的 last_assistant_message，拿來當 fallback。"""
    path = os.path.join(reports_dir, "%s.json" % agent_id)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("report") or ""
    except (OSError, ValueError):
        return ""


def rebuild(rows, projects_root, judge_hook, corpus_out,
            archive_hook=None, reports_out=None, reports_dir=None, env=None):
    """逐列跑 hook 重建。回傳計數，不動任何既有檔案。"""
    summary = {"rebuilt": 0, "no_transcript": 0, "hook_produced_nothing": 0}
    base_env = dict(os.environ if env is None else env)
    base_env["EVAL_CORPUS"] = corpus_out
    if reports_out:
        base_env["SUBAGENT_REPORT_DIR"] = reports_out
    for row in rows:
        agent_id = row.get("agent_id") or ""
        tpath = find_transcript(agent_id, projects_root)
        if not tpath:
            summary["no_transcript"] += 1
            continue
        last = _old_last_message(agent_id, reports_dir) if reports_dir else ""
        payload = json.dumps(build_payload(row, tpath, last))
        before = os.path.getsize(corpus_out) if os.path.exists(corpus_out) else 0
        subprocess.run([judge_hook], input=payload, text=True,
                       capture_output=True, env=base_env)
        after = os.path.getsize(corpus_out) if os.path.exists(corpus_out) else 0
        if after > before:
            summary["rebuilt"] += 1
        else:
            summary["hook_produced_nothing"] += 1
            continue
        if archive_hook and reports_out:
            subprocess.run([archive_hook], input=payload, text=True,
                           capture_output=True, env=base_env)
    return summary


def merge_rows(original, rebuilt, target):
    """換上去的內容 = 沒重建到的原列 + 重建好的列 + 重建期間才進來的列。

    只有成功重評的列會被取代，其餘原列一律留著——否則 `--limit` 或 hook 中途沒產出
    時，沒處理到的那些列會被換掉的檔案吃掉。

    另外 hook 是全域的，任何 session 的 subagent 結束都會 append 到同一個 corpus，
    所以換檔前重讀一次目標檔，把開跑當下還沒看過的 agent_id 撿回來。
    """
    rebuilt_ids = {r.get("agent_id") for r in rebuilt}
    original_ids = {r.get("agent_id") for r in original}
    kept = [r for r in original if r.get("agent_id") not in rebuilt_ids]
    late = [r for r in _read_jsonl(target)
            if r.get("agent_id") not in original_ids
            and r.get("agent_id") not in rebuilt_ids]
    return kept + list(rebuilt) + late


def commit(replacement, target):
    """把 replacement 換上去，原檔備份。回傳備份路徑（原本沒東西就回 None）。"""
    backup = None
    if os.path.exists(target):
        stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = "%s.bak-%s" % (target, stamp)
        n = 1
        while os.path.exists(backup):
            backup = "%s.bak-%s-%d" % (target, stamp, n)
            n += 1
        shutil.move(target, backup)
    shutil.move(replacement, target)
    return backup


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="實際換檔，預設只報告")
    ap.add_argument("--limit", type=int, help="只處理前 N 列，先試水溫用")
    ap.add_argument("--corpus", default=os.path.join(EVAL_DIR, "corpus.jsonl"))
    ap.add_argument("--reports", default=os.path.join(EVAL_DIR, "reports"))
    ap.add_argument("--projects", default=PROJECTS)
    ap.add_argument("--judge-hook", default=JUDGE_HOOK)
    ap.add_argument("--archive-hook", default=ARCHIVE_HOOK)
    args = ap.parse_args(argv)

    rows = _read_jsonl(args.corpus)
    if not rows:
        print("corpus 是空的或不存在：%s" % args.corpus)
        return 1
    stale = [r for r in rows if r.get("report_source") != "handback"]
    print("corpus 共 %d 列，其中 %d 列是用 last_assistant_message 評的" % (len(rows), len(stale)))
    if args.limit:
        stale = stale[:args.limit]
        print("--limit %d：這次只處理前 %d 列" % (args.limit, len(stale)))

    recoverable = sum(1 for r in stale if find_transcript(r.get("agent_id") or "",
                                                          args.projects))
    print("transcript 還在、可重評：%d 列（其餘 %d 列沒救）"
          % (recoverable, len(stale) - recoverable))
    if not args.apply:
        print("\n只報告。要實際重建加 --apply（會呼叫 Jev，每筆約 $0.00008）")
        return 0

    for hook in (args.judge_hook, args.archive_hook):
        if not os.path.exists(hook):
            print("找不到 hook：%s（先 chezmoi apply）" % hook)
            return 1

    tmp = tempfile.mkdtemp(prefix="backfill-")
    corpus_out = os.path.join(tmp, "corpus.jsonl")
    reports_out = os.path.join(tmp, "reports")
    os.makedirs(reports_out)
    print("\n重建中…")
    summary = rebuild(stale, args.projects, args.judge_hook, corpus_out,
                      archive_hook=args.archive_hook, reports_out=reports_out,
                      reports_dir=args.reports)
    print("  重建 %d 列 / transcript 不在 %d 列 / hook 沒產出 %d 列"
          % (summary["rebuilt"], summary["no_transcript"],
             summary["hook_produced_nothing"]))
    if not summary["rebuilt"]:
        print("沒有任何一列重建成功，不換檔。")
        return 1

    merged_rows = merge_rows(rows, _read_jsonl(corpus_out), args.corpus)
    merged = os.path.join(tmp, "merged.jsonl")
    with open(merged, "w", encoding="utf-8") as fh:
        for r in merged_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    backup = commit(merged, args.corpus)
    print("corpus 已換上，原檔備份在 %s" % backup)
    moved = 0
    for src in glob.glob(os.path.join(reports_out, "*.json")):
        shutil.move(src, os.path.join(args.reports, os.path.basename(src)))
        moved += 1
    print("reports/ 更新 %d 份（同名直接覆蓋，內容是同一次 dispatch 的完整報告）" % moved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
