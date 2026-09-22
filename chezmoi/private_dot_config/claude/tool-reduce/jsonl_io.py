"""共用的 best-effort JSONL 讀取器。

tr-stats 與 tr-eval 吃的是同一批封存檔案（decisions.jsonl／tombstones.jsonl／
restores.jsonl），而且是同一種半寫壞的風險：store._append（見 store.py）是
盡力而為、不保證 atomic，session 目錄跟封存區各自獨立寫，任一份失敗不影響
另一份。兩支工具原本各自維護一份幾乎一樣的 read_jsonl，容易漂移成兩種不同
的容錯行為（例如其中一份忘記更新、或悄悄改了篩選條件）；統一搬進這支模組，
兩邊 import 同一份函式（task-9）。

篩選規則：解析失敗的行、或解析成功但不是字典的值（裸字串、list、數字、
null——例如整份檔案被截斷成一行）都在這一層濾掉，下游（rollup()／
classify()）才能放心假設收到的都是字典，不用在每個欄位存取前重新驗證
『這筆紀錄本身是不是字典』。

skip_counter 是選擇性參數：沒帶行為不變；帶了的話是一個單一元素的 list
（`[0]` 這種），每跳過一行（解析失敗、或解析成功但不是 dict）就 +1——
呼叫端用它累計『讀檔這一關』的略過筆數，跟下游自己那關（收到已經是
dict、但欄位形狀不對的紀錄）的略過筆數合併成一個總數，讓使用者看得到
「這次統計/分類實際上略過了多少筆」，不是悄悄吞掉（task-8 fix-round 2
先在 tr-stats 定下這個契約，task-9 的 tr-eval 原樣繼承）。
"""
import json
import os


def is_full_mode(rec):
    """這筆紀錄是不是 `full` 模式寫的 —— 也就是「這次真的從 tool output
    刪了東西」，不是 shadow 模式的演練。

    PostToolUse hook 在 shadow 模式下一樣會寫決策與墓碑紀錄（那正是它的
    用途：累積資料但不動 agent 看到的東西），而兩種紀錄會混進同一份
    append-only 的 archive/，三支離線工具讀的都是它。README 的上線流程
    就是先 shadow 再 full，所以混在一起是預期會發生的事，不是意外。

    沒有 `mode` 欄位的紀錄當成 full：那是這個欄位加上去以前寫的紀錄，
    而那個時候 shadow 跟 full 本來就分不出來，假裝分得出來只會把猜測
    當成事實。

    shadow 的紀錄對每支工具的傷害不同：tr-stats 會報出根本沒發生的節省
    （「省了 6,804 字元、還原率 0.0%」，而實際上沒有任何一份輸出被改過）；
    tr-eval 受傷最重，shadow 模式下 agent 看得到全文，獨有詞自然會再出現，
    每一段都會被算成沉默誤刪。"""
    if not isinstance(rec, dict):
        return False
    mode = rec.get("mode")
    return mode is None or mode == "full"


def filter_full_mode(records, counter=None):
    """濾掉非 full 模式的紀錄。counter 是選擇性的單一元素 list，濾掉幾筆
    就 +=，讓呼叫端可以印出來 —— 跟 skip_counter 一樣的契約，安靜吞掉
    才是這個專案一直在避免的事。"""
    out = [r for r in records if is_full_mode(r)]
    if counter is not None:
        counter[0] += len(records) - len(out)
    return out


def read_jsonl(path, skip_counter=None):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                if skip_counter is not None:
                    skip_counter[0] += 1
                continue
            if isinstance(rec, dict):
                out.append(rec)
            elif skip_counter is not None:
                skip_counter[0] += 1
    return out
