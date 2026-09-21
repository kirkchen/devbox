"""從 Claude Code transcript 收 subagent 的執行結果，以 tool_use_id 為 key。

hook 只知道「決定了什麼」，結果要事後從 transcript 撈。兩邊靠 tool_use_id 接。
"""
import json, glob, os, re, collections

NOTIF = re.compile(r'<task-notification>(.*?)</task-notification>', re.S)
def _f(tag, s):
    m = re.search(rf'<{tag}>(.*?)</{tag}>', s, re.S)
    return m.group(1) if m else None

def harvest(project_glob="~/.claude/projects/*"):
    files = [p for d in glob.glob(os.path.expanduser(project_glob))
             for p in glob.glob(os.path.join(d, "*.jsonl"))]
    out = {}
    rework = collections.defaultdict(set)   # file -> task numbers that needed fixes
    dispatch_file = {}
    for f in files:
        try:
            lines = open(f, encoding="utf-8").read().splitlines()
        except Exception:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if "task-notification" in line:
                for body in NOTIF.findall(line):
                    body = body.replace("\\n", "\n")
                    tid = _f("tool-use-id", body)
                    if not tid:
                        continue
                    d = out.setdefault(tid, {})
                    d.update({"status": _f("status", body)})
                    for k, tag in (("subagent_tokens", "subagent_tokens"),
                                   ("tool_uses", "tool_uses"),
                                   ("duration_ms", "duration_ms")):
                        v = _f(tag, body)
                        if v:
                            d[k] = int(v)
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            msg = ev.get("message") or {}
            content = msg.get("content")
            tur = ev.get("toolUseResult")
            if isinstance(content, list):
                for x in content:
                    if not isinstance(x, dict):
                        continue
                    if x.get("type") == "tool_use" and x.get("name") in ("Task", "Agent"):
                        inp = x.get("input") or {}
                        dispatch_file[x["id"]] = os.path.basename(f)
                        out.setdefault(x["id"], {}).update({
                            "description": inp.get("description"),
                            "subagent_type": inp.get("subagent_type"),
                            "model_requested": inp.get("model"),
                            "ts": ev.get("timestamp", "")[:19],
                        })
                        d = inp.get("description") or ""
                        if re.match(r'^Re-review Task', d) or re.search(r'fix round', d, re.I):
                            m = re.search(r'Task (\d+)', d)
                            if m:
                                rework[os.path.basename(f)].add(m.group(1))
                    if x.get("type") == "tool_result" and isinstance(tur, dict) and "resolvedModel" in tur:
                        d = out.setdefault(x.get("tool_use_id"), {})
                        d["model_resolved"] = tur["resolvedModel"]
                        if tur.get("agentId"):
                            d["agent_id"] = tur["agentId"]
    for tid, d in out.items():
        desc = d.get("description") or ""
        m = re.search(r'Task (\d+)', desc)
        d["needed_fix_round"] = (m.group(1) in rework[dispatch_file.get(tid, "")]) \
            if (m and re.match(r'^Implement Task', desc)) else None
    return out


def by_agent_id(project_glob="~/.claude/projects/*"):
    """agent_id -> outcome（含 tool_use_id）。corpus 的列用 agent_id 當鍵。"""
    o = harvest(project_glob)
    return {v["agent_id"]: {**v, "tool_use_id": k}
            for k, v in o.items() if v.get("agent_id")}
