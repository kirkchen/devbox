"""把路由決策接上 Layer 1 的完成度分數（corpus.jsonl）。

`review.py` 本來只看決策紀錄與 transcript 用量——那只答得出「跑了幾輪」，答不出
「產出有沒有比較差」。這裡負責 corpus 的讀取與分組，讓覆盤能並排看
「router 改過的 dispatch」與「沒動的」在 Layer 1 四題上的分布。

**這個比較沒有證據力，只是敘述。** 兩個理由：

1. 兩群不可比。router 專挑它判斷簡單的任務降級，所以兩群本來就是不同難度的工作。
   差異為零可能代表降級沒害處，也可能代表它只降級了本來就簡單的。
2. Layer 1 是 Jev 判 Jev 自己的路由結果，有循環性，本來就不當 ground truth
   （見 README 的 Layer 1 一節）。要有證據力得走 Layer 2 盲標加人工基準。

所以 `describe()` 一定把這段警語跟數字一起印出去，不讓表格單獨存在。
"""
import collections
import json
import os
import statistics

DEFAULT_CORPUS = os.path.expanduser(
    os.environ.get("EVAL_CORPUS", "~/.local/share/model-router-eval/corpus.jsonl"))

SIGNALS = (
    ("addressed_everything", "addressed_everything", "noul"),
    ("signs_of_incompleteness", "signs_of_incompleteness", "noul"),
    ("output_depth", "output_depth", "score"),
)


def load_corpus(path=DEFAULT_CORPUS):
    """agent_id -> 該 agent 的所有 Layer 1 列。

    一個 agent 交回幾次就有幾列（見 transcript.handback_positions），全部留著。
    """
    by_agent = collections.defaultdict(list)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            agent_id = row.get("agent_id")
            if agent_id:
                by_agent[agent_id].append(row)
    return dict(by_agent)


def _summarise(rows):
    summary = {"n": len(rows),
               "needs_layer2": sum(1 for r in rows if r.get("needs_layer2"))}
    for name, question, field in SIGNALS:
        values = [(r.get("screen") or {}).get(question, {}).get(field) for r in rows]
        values = [v for v in values if v is not None]
        summary[name] = statistics.median(values) if values else None
    return summary


def compare(decisions, corpus_by_agent):
    """依「router 有沒有實際改掉模型」分兩群，各自算 Layer 1 的中位數。

    決策接不到 Layer 1 列的（corpus 沒有那個 agent）算進 `unmatched`，不併進任何一群，
    否則會看不出覆蓋率有多低。
    """
    groups = {"changed": [], "untouched": []}
    unmatched = 0
    for decision in decisions:
        agent_id = (decision.get("outcome") or {}).get("agent_id")
        rows = corpus_by_agent.get(agent_id) or []
        if not rows:
            unmatched += 1
            continue
        key = "changed" if decision.get("model_applied") else "untouched"
        groups[key].extend(rows)
    result = {key: _summarise(rows) for key, rows in groups.items()}
    result["unmatched"] = unmatched
    return result


def describe(result):
    """回傳可直接印的行；數字與警語綁在一起，不讓表格單獨存在。

    刻意不排表格：標籤是中文全形，`%-10s` 按字元數補寬度會跟半形數字對不齊，
    所以改成每群一行、標籤貼著數字。
    """
    lines = []
    total = result["changed"]["n"] + result["untouched"]["n"]
    if not total:
        lines.append("  corpus 接不到任何一筆決策"
                     "（Layer 1 沒開，或 corpus 在別的位置）")
        return lines
    for key, label in (("changed", "路由改過"), ("untouched", "路由沒動")):
        g = result[key]
        if not g["n"]:
            lines.append("  %s：無" % label)
            continue
        lines.append(
            "  %s %d 次交付 — 有處理到 %.2f、做一半 %.2f、深度 %.2f、"
            "待 Layer 2 %d (%.0f%%)"
            % (label, g["n"], g["addressed_everything"],
               g["signs_of_incompleteness"], g["output_depth"],
               g["needs_layer2"], 100.0 * g["needs_layer2"] / g["n"]))
    if result["unmatched"]:
        lines.append("  （另有 %d 筆決策在 corpus 找不到對應的 Layer 1 列）"
                     % result["unmatched"])
    lines.append("  ⚠ 這是敘述不是證據：router 專挑判斷簡單的任務降級，兩群難度本來就不同；")
    lines.append("    且 Layer 1 是 Jev 判 Jev 自己的結果，有循環性。要下結論得走 Layer 2 盲標。")
    return lines
