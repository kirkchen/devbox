#!/usr/bin/env python3
"""門檻重放與調校。

每段的 Jev 原始分數都存在 decisions.jsonl，所以調門檻只是拿同一批答案重算 ——
零 API 成本、零延遲，幾百種組合的網格搜尋幾秒跑完。

目標函數的形狀刻意分兩步、順序不能倒：
  1. 先篩：候選門檻重放後的沉默誤刪率（silent_miss_rate）不得高於現行設定。
  2. 才比：在通過第 1 步的子集合裡，按省下的字元數由大到小排序。
寫成「誤刪率在上限內、省最多」聽起來一樣，實際上是同一個排序、不同的優先
順序——會讓搜尋為了一點點節省，把最貴的錯誤（沉默誤刪：agent 需要卻沒去
拿）推到上限邊緣。--allow-worse 才能解除這個上限，且必須是使用者明講的
旗標，不能是預設行為（見 search()／main() 的說明）。

門檻能不能真的套用，還有第二道閘門：人工基準（human_baseline.json）。
Jev 的分數、Layer 1 的三態分類、這支重算的候選，全部是同一套系統在給自己
的作業打分數；標籤只要不夠新、不夠多、或跟人的判斷對不上，調出來的門檻會
往「大家一起看走眼」的方向收斂，同時每個自動算出來的指標卻都在變好看。
唯一從這個迴圈外面進來的訊號是人工基準，所以基準不合格時 --apply 要拒絕
套用並說明理由，不是印個警告接著照套（check_baseline()／main()）。

用法：
  tr-tune.py                # 只列候選，不套用
  tr-tune.py --apply        # 套用最佳候選（需通過人工基準閘門）
  tr-tune.py --apply --allow-worse   # 明確允許候選比現行更危險，才能解除上限
"""
import argparse
import importlib.util
import itertools
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import drop_policy
import store

# tr_eval 提供 classify／summarize／transcript_after／read_jsonl（read_jsonl
# 其實是 jsonl_io.read_jsonl 的別名，tr-stats／tr-eval／這裡三邊共用同一份
# 容錯規則，見 jsonl_io.py 的說明）。executable_tr-eval.py 檔名帶連字號、
# 不是合法的 import 識別字，跟既有測試（tests/python/test_eval.py 的
# load()）用同一招：spec_from_file_location 直接載入這個檔案。
#
# 兩個檔名都要試：chezmoi 部署時會把 `executable_` 前綴拿掉（實測
# `chezmoi target-path` 的答案是 ~/.config/claude/tool-reduce/tr-eval.py），
# 所以「原始碼樹裡叫 executable_tr-eval.py、真正跑的環境裡叫 tr-eval.py」
# 是兩個都會出現的名字。只認前者的話，這支工具部署後在 import 階段就
# FileNotFoundError，連 main() 都進不去——而它正是「先在 2.2% 上線、之後
# 再從遙測重新推導門檻」那句話的整個機制。tr-stats／tr-eval 沒有這個問題，
# 它們不載入兄弟檔案。
_EVAL_NAMES = ("executable_tr-eval.py", "tr-eval.py")


def _load_tr_eval():
    for name in _EVAL_NAMES:
        path = os.path.join(HERE, name)
        if os.path.exists(path):
            spec = importlib.util.spec_from_file_location("tr_eval", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ImportError(
        "tr-eval not found next to tr-tune (looked for "
        + " / ".join(_EVAL_NAMES) + " in " + HERE + ")")


tr_eval = _load_tr_eval()

MIN_LABELLED = 20        # 人工基準至少要幾筆
MIN_AGREEMENT = 0.7      # 人機一致率下限
MAX_NEW_SINCE = 200      # 基準之後新增樣本超過這個數就算過期
# 自動調校至少要有幾筆可重放的決策紀錄。網格有 132 格，紀錄太少的時候
# 每一格都是在對雜訊過擬合——而且有一個更難看的失效模式：紀錄是空的時候
# 每個候選的 silent_miss_rate 都是 0.0、saved 都是 0，132 個候選全部通過
# 「不得高於現行」這關、全部並列，排序穩定，cands[0] 就是網格的第一格，
# 於是 --apply 會寫下整個網格裡最激進的一組門檻（noise_min=0.4
# uniq_max=0.1）。對照實測的 noise p50 是 0.33，那會刪掉每一份 tool
# result 的一大塊。人工基準那道閘門只驗三個自填數字的「形狀」，從來沒有
# 對照過封存區裡到底有沒有作業。
MIN_DECISIONS = 50


def _thresholds_path():
    """跟 store.root() 同一個理由：每次呼叫才解析 TOOL_REDUCE_THRESHOLDS，
    不在模組載入當下凍結成常數，這樣測試才能在同一個行程裡把它指向不同的
    暫存路徑（task-7 抓到的『先讀早、後設環境變數看到舊值』那個 bug 形狀，
    tr-stats／tr-eval 對 TOOL_REDUCE_HOME 已經是這個公式，這裡同理）。"""
    return os.path.expanduser(os.environ.get(
        "TOOL_REDUCE_THRESHOLDS", "~/.config/claude/tool-reduce/thresholds.json"))


class BaselineTooThin(Exception):
    """人工基準不足以支撐自動調校。"""


def _validate_field(b, field, label):
    """人工基準的三個欄位（labelled／agreement／new_since）型別不對時，
    不能『退回預設值 0 再去比大小』——labelled／agreement 是『數字越大越
    安全』，退回 0 剛好會被『太少／太低』這關擋下來，意外安全；但
    new_since 是『數字越大越危險』，退回 0 等於讓『基準是否過期』這關
    永遠不會觸發，沉默放行。同一套『型別不對就當 0』的預設規則，套在
    比較方向相反的兩種欄位上會有相反的安全後果——不該讓比較方向決定
    型別錯誤時是否安全。所以型別不對、缺欄位（.get 回傳 None，跟明確寫
    null 是同一種『這個數字不可信』）、布林值（True/False 是 int 的子
    類別，isinstance 檢查會誤放行，必須排除）、或負值，一律直接判定這
    關不通過，不看比較方向、也不嘗試補一個看似合理的預設值。

    fix round 2：同一個家族還有一個成員——`nan`。任何跟 `nan` 的比較
    （`<`、`>`、`==`）都是 False，所以寫成比較式的關卡對 `nan` 永遠不會
    觸發，三個欄位同時失守（不像 fix round 1 的 bug 只打穿 new_since
    一個方向）。`json.loads` 預設接受裸的 `NaN`／`Infinity`／`-Infinity`
    字面值，所以這不是理論上的輸入形狀。`math.isfinite` 一次擋掉 `nan`
    跟兩個無窮——`inf` 也要擋：`new_since=inf` 本來就會被
    `> MAX_NEW_SINCE` 正確擋下來，但 `labelled=inf`／`agreement=inf` 會
    通過『越大越好』方向的比較，跟原本 `new_since` 那個 bug 是同一個
    『比較方向決定型別錯誤是否安全』的錯誤形狀，只是這次換成 `inf`。"""
    v = b.get(field)
    if (not isinstance(v, (int, float)) or isinstance(v, bool)
            or not math.isfinite(v) or v < 0):
        raise BaselineTooThin(
            f"人工基準欄位「{field}」（{label}）缺漏或型別不對："
            f"{v!r}，需要是一個非負且有限的數字")
    return v


def check_baseline(b):
    """人工基準是唯一從迴圈外進來的訊號。不合格就拒絕套用並說明原因，
    不是印警告接著照套——這支函式只做「行不行」的判斷，說明文字留給
    呼叫端決定怎麼呈現。三個欄位的型別驗證（_validate_field）在比較
    數值大小之前，任何一個欄位型別不對就直接拒絕，不會被其他欄位的
    正常值掩蓋。"""
    if not isinstance(b, dict):
        b = {}

    labelled = _validate_field(b, "labelled", "人工標註筆數")
    if labelled < MIN_LABELLED:
        raise BaselineTooThin(
            f"人工基準只有 {labelled:g} 筆，需要至少 {MIN_LABELLED} 筆")

    agreement = _validate_field(b, "agreement", "人機一致率")
    if agreement < MIN_AGREEMENT:
        raise BaselineTooThin(
            f"人機一致率 {agreement:.0%} 低於門檻 {MIN_AGREEMENT:.0%}")

    new_since = _validate_field(b, "new_since", "基準之後新增樣本數")
    if new_since > MAX_NEW_SINCE:
        raise BaselineTooThin(
            f"基準之後新增 {new_since:g} 筆，超過 {MAX_NEW_SINCE}，基準已過期")


def _chunk_lists(d):
    """decision 記錄裡的 chunks 拆成 (chunks, scores, chars) 三條等長清單
    餵給 drop_policy.decide。跟 tr-eval._valid_chunks 面對的是同一批可能
    半寫壞的封存檔案，形狀不對就退化成空清單（等同這筆決策沒有段落可
    重放），不丟例外——不然一筆壞紀錄就讓整次重放中斷，等於用一次讀檔
    失敗吞掉後面所有還算得出來的證據。"""
    empty = [], [], []
    if not isinstance(d, dict):
        return empty
    chunks = d.get("chunks")
    if not isinstance(chunks, list):
        return empty
    good = [c for c in chunks if isinstance(c, dict)]
    if len(good) != len(chunks):
        return empty  # 混進非 dict 元素：整筆的段落順序信不過，不重放
    scores = [c.get("scores") if isinstance(c.get("scores"), dict) else {} for c in good]
    chars = []
    for c in good:
        ch = c.get("chars")
        chars.append(ch if isinstance(ch, (int, float)) and not isinstance(ch, bool) else 0)
    return good, scores, chars


def replay(decisions, thresholds):
    """用給定門檻重新決策，回傳省下多少。走 drop_policy.decide——跟線上
    PostToolUse hook 呼叫的是同一份函式，位置地板（頭尾不刪）也在
    decide() 內部，離線重放不會漏掉、也不會重新發明一份決策邏輯。"""
    saved = dropped = 0
    for d in decisions:
        chunks, scores, chars = _chunk_lists(d)
        if not chunks:
            continue
        for ch, is_drop in zip(chars, drop_policy.decide(scores, chars, thresholds)):
            if is_drop:
                saved += ch
                dropped += 1
    return {"saved": saved, "dropped": dropped}


def _relabel(decisions, thresholds, later_text):
    """用候選門檻重放後，重新跑 Layer 1 三態分類，藉此估計這組候選的
    沉默誤刪率。restores 刻意傳空集合——真實的 restores.jsonl 記的是
    「現行門檻實際刪了什麼、後來被還原了什麼」，換一組候選門檻後被刪的
    段落集合會不一樣，把現行的還原紀錄套到候選的裁切結果上，會把「候選
    也剛好刪到同一段」的巧合當成這段一定會被還原，讓某些候選看起來比
    實際更安全。文字比對雖然是近似指標，但至少是對「這組候選會刪什麼」
    算出來的，不是借用另一組門檻的還原紀錄。"""
    shadow = []
    for d in decisions:
        chunks, scores, chars = _chunk_lists(d)
        if not chunks:
            shadow.append(d)
            continue
        mask = drop_policy.decide(scores, chars, thresholds)
        new_chunks = [dict(c, dropped=bool(m)) for c, m in zip(chunks, mask)]
        shadow.append(dict(d, chunks=new_chunks))
    return tr_eval.classify(shadow, [], later_text)


def _default_grid():
    return [
        {"noise_min": n, "uniq_max": u,
         "min_chunks": drop_policy.DEFAULTS["min_chunks"],
         "max_drop_ratio": drop_policy.DEFAULTS["max_drop_ratio"]}
        for n, u in itertools.product(
            [round(x * 0.05, 2) for x in range(8, 20)],     # 0.40 .. 0.95
            [round(x * 0.05, 2) for x in range(2, 13)])]    # 0.10 .. 0.60


def search(decisions, baseline_silent_miss, later_text, grid=None):
    """網格搜尋，兩步順序不能倒：先只留下沉默誤刪率不高於
    baseline_silent_miss 的候選，才在這個子集合裡按省下的字元數由大到小
    排序。呼叫端決定 baseline_silent_miss 是多少——main() 預設傳現行設定
    的沉默誤刪率（--allow-worse 時放寬成 1.0），這支函式本身不內建任何
    「上限內找最大」的邏輯，也不知道 --allow-worse 這回事，安全與否的
    政策留在呼叫端一個地方決定。"""
    grid = grid if grid is not None else _default_grid()
    out = []
    for t in grid:
        rows = _relabel(decisions, t, later_text)
        s = tr_eval.summarize(rows)
        if s["silent_miss_rate"] > baseline_silent_miss:
            continue
        r = replay(decisions, t)
        out.append({**t, "saved": r["saved"], "dropped": r["dropped"],
                    "silent_miss_rate": s["silent_miss_rate"]})
    return sorted(out, key=lambda c: -c["saved"])


def main():
    ap = argparse.ArgumentParser(description="門檻重放與調校：拿累積的 Jev 原始分數零成本重算候選門檻。")
    ap.add_argument("--apply", action="store_true",
                    help="套用最佳候選門檻（需通過人工基準閘門）。不給只列候選、不寫任何檔案。")
    ap.add_argument("--allow-worse", action="store_true",
                    help="明確允許用安全性換節省：解除沉默誤刪率不得高於現行的上限。"
                         "不給這個旗標，這件事就不會發生。")
    a = ap.parse_args()

    home = store.root()
    base = os.path.join(home, "archive")

    read_skip = [0]
    shadow_skip = [0]
    # shadow 模式的紀錄在這一層就濾掉（見 jsonl_io.is_full_mode）。門檻
    # 是從這批紀錄推導出來的，混進「沒有真的刪過東西」的判斷會讓上限
    # 跟排名都失真。
    decisions = tr_eval.filter_full_mode(
        tr_eval.read_jsonl(os.path.join(base, "decisions.jsonl"), read_skip),
        shadow_skip)
    restores = tr_eval.read_jsonl(os.path.join(base, "restores.jsonl"), read_skip)
    by_id = {d["decision_id"]: d for d in decisions
             if isinstance(d, dict) and isinstance(d.get("decision_id"), str)}
    transcript_dir = os.environ.get("TOOL_REDUCE_TRANSCRIPT_DIR") or None
    later = {did: tr_eval.transcript_after(did, by_id, transcript_dir) for did in by_id}

    classify_skip = [0]
    current = tr_eval.summarize(
        tr_eval.classify(decisions, restores, later, skip_counter=classify_skip))
    total_skipped = read_skip[0] + classify_skip[0]
    if total_skipped:
        print(f"注意：{total_skipped} 筆紀錄格式不對，已略過、未列入以下重算"
              "（可能是半寫壞的紀錄檔）\n")
    if shadow_skip[0]:
        print(f"注意：{shadow_skip[0]} 筆 shadow 模式的決策未列入以下重算"
              "（那些段落沒有真的從 tool output 消失）\n")

    if a.allow_worse:
        ceiling = 1.0
        print(f"現行沉默誤刪率 {current['silent_miss_rate']:.1%}")
        print("=" * 60)
        print("警告：--allow-worse 已解除沉默誤刪率安全上限。")
        print("以下候選可能比現行設定更危險，用安全性換節省，套用前請人工複核。")
        print("=" * 60 + "\n")
    else:
        ceiling = current["silent_miss_rate"]
        print(f"現行沉默誤刪率 {current['silent_miss_rate']:.1%}（候選不得高於此值）\n")

    # 有多少筆決策真的能重放（有段落、形狀過得了 _chunk_lists）。這是
    # 「有沒有作業可以打分數」的唯一實測數字，跟人工基準那三個自填的欄位
    # 無關 —— 見 MIN_DECISIONS 旁的說明。
    replayable = sum(1 for d in decisions if _chunk_lists(d)[0])

    cands = search(decisions, ceiling, later)
    print(f"  {'noise_min':>10}{'uniq_max':>10}{'省下':>12}{'段數':>7}{'沉默誤刪':>10}")
    for c in cands[:10]:
        print(f"  {c['noise_min']:>10.2f}{c['uniq_max']:>10.2f}{c['saved']:>12,}"
              f"{c['dropped']:>7}{c['silent_miss_rate']:>10.1%}")
    if not cands:
        print("\n沒有合格的候選（網格裡沒有任何組合的沉默誤刪率不高於現行），門檻維持不變。")
    # 刻意不是 elif：候選是空集合、而且紀錄又太少，是兩件獨立的事，
    # 使用者兩件都該聽到。掛成 elif 的話「沒有合格的候選」會把「紀錄
    # 太少」這句蓋掉，而後者才是他真正該先處理的那一件。
    if replayable < MIN_DECISIONS:
        print(f"\n注意：封存區只有 {replayable} 筆可重放的決策紀錄（需要至少 "
              f"{MIN_DECISIONS} 筆才能 --apply）。上面的排名不足以當作依據。")

    if not a.apply:
        print("\n（只是列出候選，不套用、不寫任何檔案。要套用加 --apply。）")
        return 0

    bpath = os.path.join(base, "human_baseline.json")
    try:
        if os.path.exists(bpath):
            with open(bpath, encoding="utf-8") as fh:
                b = json.load(fh)
        else:
            b = {}
    except json.JSONDecodeError as e:
        # 檔案存在但不是合法 JSON（寫壞、寫到一半）——跟 store.load_chunk
        # 之前修過的同一類問題：讓例外原樣往外逸出會印出直譯器的原生
        # traceback（內含這支腳本的絕對路徑），洩漏內部實作路徑，而且不是
        # 「拒絕套用並說明原因」該有的樣子。這裡攔下來，改用跟
        # BaselineTooThin 同一種措辭拒絕，不印檔案的原始例外內容。
        print(f"\n拒絕套用：{bpath} 不是合法的 JSON（{e.msg}，第 {e.lineno} 行第 "
              f"{e.colno} 欄），人工基準檔案已損毀或格式不對")
        print("需要先修好這份檔案（或重新產生）才能自動調校。")
        return 1

    try:
        check_baseline(b)
    except BaselineTooThin as e:
        print(f"\n拒絕套用：{e}")
        print(f"補標之後更新 {bpath}。穩態下大約每累積 200 筆補標 10 筆。")
        return 1

    # 人工基準是「有沒有人在外面把關」；這一關是「裡面到底有沒有作業」。
    # 前者只驗三個自填數字的形狀，從來不對照封存區，所以一份看起來完全
    # 合格的 human_baseline.json 配上一個空的封存區，過去會一路寫到底。
    if replayable < MIN_DECISIONS:
        print(f"\n拒絕套用：封存區只有 {replayable} 筆可重放的決策紀錄，"
              f"需要至少 {MIN_DECISIONS} 筆。")
        print("紀錄太少時 132 格的網格幾乎都是在對雜訊過擬合；一筆都沒有的時候"
              "每一格並列（省 0 字元、沉默誤刪 0%），排序後的第一名只是網格的"
              "第一格，也就是最激進的那一組門檻。")
        print(f"（{MIN_DECISIONS} 這個數字是人訂的判斷，不是量出來的：它只是"
              "「網格不再明顯在擬合雜訊」的下限。等 restores.jsonl 累積出真實的"
              "還原遙測，這個門檻應該往上調。）")
        return 1

    if not cands:
        print("\n沒有合格的候選，門檻不變、未寫入任何檔案。")
        return 0

    # 全部並列在「省 0 字元」時，cands[0] 不是量出來的最佳解，只是網格的
    # 第一格（排序是穩定的）。這跟「沒有合格的候選」不一樣：那是有結論、
    # 結論是維持現狀；這是根本分不出高下。
    if not any(c["saved"] > 0 for c in cands):
        print(f"\n拒絕套用：{len(cands)} 個合格候選全部省下 0 字元，分不出高下。"
              "排序後的第一名只是網格的第一格，不是量出來的結果。")
        return 1

    best = cands[0]
    thresholds_path = _thresholds_path()
    out_dir = os.path.dirname(thresholds_path)
    os.makedirs(out_dir, exist_ok=True)
    # 寫到同目錄下的暫存檔再 os.replace，不直接開 thresholds_path 寫——後者
    # 中途被中斷（行程被殺、磁碟滿）會留下一份寫到一半的截斷檔案。
    # drop_policy.load() 讀到解析失敗的 JSON 時會退回 DEFAULTS，所以爆炸
    # 半徑本來就不大，但 os.replace 在同一個檔案系統上是原子操作，讓這個
    # 失敗模式直接不可能發生，而不只是可以從容復原。
    fd, tmp_path = tempfile.mkstemp(dir=out_dir, prefix=".thresholds-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({k: best[k] for k in drop_policy.DEFAULTS}, fh, indent=2)
        os.replace(tmp_path, thresholds_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    print(f"\n已套用：noise_min={best['noise_min']} uniq_max={best['uniq_max']}"
          f"  寫入 {thresholds_path}")
    if a.allow_worse:
        print("（此次套用經 --allow-worse 放行，沉默誤刪率可能高於先前設定。）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
