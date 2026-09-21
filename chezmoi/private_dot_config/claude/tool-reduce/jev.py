"""TypeSafe Jev client。只用標準函式庫，與 model-router 的做法一致。

金鑰來自 ~/.config/claude/typesafe.env 的 TYPESAFE_API_KEY，逐行解析、不 source shell。
金鑰永不進入錯誤訊息或紀錄。
"""
import json, os, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.environ.get("TOOL_REDUCE_API", "https://api.typesafe.ai/v1/systemone")
_SPEC = None


def spec():
    global _SPEC
    if _SPEC is None:
        with open(os.path.join(HERE, "questions.json"), encoding="utf-8") as fh:
            _SPEC = json.load(fh)
    return _SPEC


def load_env(path):
    """讀 KEY=VALUE 檔。不 source shell，避免執行任意內容。已存在的環境變數不覆寫。"""
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass


def build_questions(n_chunks):
    qs = {}
    for name, q in spec()["questions"].items():
        for i in range(n_chunks):
            qs[f"{name}_c{i}"] = {
                "type": q["type"],
                "instructions": q["instructions"].replace("{k}", f"c{i}"),
            }
    return qs


def ask(state, questions, timeout=2.5, opener=None):
    """送一次請求，回傳 answers。任何失敗丟 RuntimeError（訊息不含金鑰）。"""
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY not set")
    body = json.dumps({"model": spec()["model"], "state": state,
                       "questions": questions}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    op = opener or urllib.request.urlopen
    try:
        with op(req, timeout=timeout) as r:
            parsed = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"jev http {e.code}") from None
    except Exception as e:
        raise RuntimeError(f"jev call failed: {type(e).__name__}") from None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("answers"), dict):
        raise RuntimeError("jev response missing answers")
    return parsed["answers"]


def scores(answers, n_chunks):
    """把 answers 攤平成每段一個 dict，缺漏填 None。"""
    names = list(spec()["questions"].keys())
    out = []
    for i in range(n_chunks):
        row = {}
        for name in names:
            a = answers.get(f"{name}_c{i}")
            v = a.get("noul") if isinstance(a, dict) else None
            row[name] = v if isinstance(v, (int, float)) else None
        out.append(row)
    return out
