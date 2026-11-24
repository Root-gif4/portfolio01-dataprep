"""試しに使ってみる用のデータ（架空）を samples/trial/ に作る。

    python samples/make_trial.py

- 受注_10-11月.csv / 入金_10-11月.csv : 120 件。よくある表記ゆれ・エラー・重複・未入金を少しだけ含む
- 受注_きれい.csv / 入金_きれい.csv   : 50 件。エラーがなく、入金もすべて一致する（「正常ならこう見える」の確認用）

受注は Shift_JIS（ショップの管理画面から出す想定）、入金は UTF-8。
名前・メールアドレス・電話番号はすべて架空のもの（メールは example.com）。
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent / "trial"

PRODUCTS = [
    ("TS-001", "Tシャツ ホワイト M", 2480),
    ("TS-002", "Tシャツ ブラック L", 2480),
    ("HD-110", "パーカー グレー L", 5980),
    ("MG-010", "マグカップ 350ml", 1650),
    ("TB-020", "タンブラー ステンレス", 2750),
    ("BG-101", "トートバッグ キャンバス", 3300),
    ("ST-205", "ステッカー 5枚セット", 550),
    ("CP-300", "キャップ ネイビー", 2980),
    ("SK-400", "ソックス 3足組", 1320),
    ("NB-500", "ノート A5 方眼", 880),
]
# 売れ方に差をつける（同じくらいだとグラフがおもしろくないため）
WEIGHTS = [14, 9, 5, 12, 6, 8, 18, 7, 10, 11]
PAY_METHODS = ["クレジットカード", "銀行振込", "コンビニ払い", "代金引換"]
PAY_WEIGHTS = [55, 15, 20, 10]
FAMILY = ["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤", "吉田", "山田", "松本", "井上", "木村"]
GIVEN = ["一郎", "花子", "翔太", "美咲", "健太", "由美", "大輔", "さくら", "拓也", "愛", "蓮", "陽菜", "悠真", "結衣", "颯"]

ORDER_HEADER = ["注文番号", "注文日", "顧客名", "メールアドレス", "電話番号", "商品コード", "商品名", "数量", "単価", "合計金額", "支払方法"]
PAY_HEADER = ["入金ID", "入金日", "注文番号", "入金額", "決済手段"]


def make_orders(rng: random.Random, count: int, first_no: int, start: date, days: int) -> list[list[str]]:
    rows = []
    for n in range(count):
        code, name, price = rng.choices(PRODUCTS, weights=WEIGHTS)[0]
        qty = rng.choices([1, 2, 3, 4, 5], weights=[50, 25, 12, 8, 5])[0]
        d = start + timedelta(days=rng.randint(0, days))
        f, g = rng.randrange(len(FAMILY)), rng.randrange(len(GIVEN))
        no = first_no + n
        rows.append([
            f"ORD-{no:06d}", d.strftime("%Y/%m/%d"), f"{FAMILY[f]} {GIVEN[g]}",
            f"customer{no % 10000:04d}@example.com", f"080-1111-{no % 10000:04d}",
            code, name, str(qty), str(price), str(qty * price),
            rng.choices(PAY_METHODS, weights=PAY_WEIGHTS)[0],
        ])
    rows.sort(key=lambda r: (r[1], r[0]))  # 注文日の順に並べる（管理画面から出した CSV らしく）
    return rows


def make_payments(orders: list[list[str]], rng: random.Random, unpaid=(), short=()) -> list[list[str]]:
    """unpaid の注文番号は入金なし、short は入金額が 1,000 円少ない。"""
    rows, seen = [], set()
    for o in orders:
        no = o[0].upper()
        if no in seen or no in unpaid:
            continue
        seen.add(no)
        amount = o[9].replace(",", "").replace("円", "").replace("，", "")
        if not amount.isdigit():
            amount = str(int(o[7]) * int(o[8])) if o[7].isdigit() and o[8].isdigit() else "0"
        if no in short:
            amount = str(int(amount) - 1000)
        try:
            ordered = date(*(int(x) for x in o[1].split("/")))
        except (TypeError, ValueError):  # 日付の書き方を変えた行・ありえない日付の行
            ordered = date(2026, 10, 1)
        paid = ordered + timedelta(days=rng.randint(0, 4))
        rows.append([paid.isoformat(), no, amount, o[10]])
    rows.sort()
    return [[f"PAY-{i:05d}", *r] for i, r in enumerate(rows, start=1)]


def write(path: Path, header: list[str], rows: list[list[str]], encoding: str) -> None:
    with path.open("w", encoding=encoding, newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rng = random.Random(20261123)

    # ---- 120 件（少しだけ問題あり）----
    orders = make_orders(rng, 120, 270001, date(2026, 10, 1), 52)
    # 整形で直るもの
    orders[3][1] = orders[3][1].replace("/", "年", 1).replace("/", "月", 1) + "日"   # 2026年10月2日
    orders[9][9] = f"{int(orders[9][9]):,}円"                                       # 「4,960円」
    orders[15][0] = orders[15][0].lower()                                          # 小文字の注文番号
    orders[22][4] = orders[22][4].translate(str.maketrans("0123456789-", "０１２３４５６７８９ー"))  # 全角の電話番号
    orders[30][3] = " " + orders[30][3].upper() + " "                               # 大文字・前後の空白
    orders[41][7] = "２"; orders[41][9] = str(2 * int(orders[41][8]))              # 全角の数量
    # エラーになるもの
    orders[50][2] = ""                                                             # 顧客名が空欄
    orders[58][3] = "customer-mail.example.com"                                    # メールアドレスの形でない
    orders[66][9] = str(int(orders[66][9]) + 300)                                  # 合計金額が 数量×単価 と合わない
    orders[74][10] = "後払い"                                                       # 使えない支払方法
    orders[83][1] = "2026/11/31"                                                   # ありえない日付
    orders[91][7] = "0"; orders[91][9] = "0"                                       # 数量が 0
    # 重複（同じ注文が2回出力された）
    orders.insert(101, list(orders[100]))
    orders.insert(111, list(orders[110]))
    write(OUT / "受注_10-11月.csv", ORDER_HEADER, orders, "cp932")

    order_nos = [o[0].upper() for o in orders]
    # まだ入金がない（数量 0 の注文も、入金はない扱い）
    unpaid = {order_nos[i] for i in (12, 47, 88, 91, 117)}
    # 入金額が 1,000 円少ない（3,000 円以上の注文から 2 件）
    big = [o[0].upper() for o in orders[30:] if o[9].isdigit() and int(o[9]) >= 3000]
    short = {big[3], big[30]}
    payments = make_payments(orders, rng, unpaid=unpaid, short=short)
    payments.append([f"PAY-{len(payments) + 1:05d}", "2026-11-21", "ORD-279999", "2480", "銀行振込"])  # 注文の見つからない入金
    write(OUT / "入金_10-11月.csv", PAY_HEADER, payments, "utf-8")

    # ---- 50 件（問題なし）----
    clean = make_orders(rng, 50, 280001, date(2026, 11, 1), 21)
    write(OUT / "受注_きれい.csv", ORDER_HEADER, clean, "cp932")
    write(OUT / "入金_きれい.csv", PAY_HEADER, make_payments(clean, rng), "utf-8")

    print(f"受注_10-11月.csv {len(orders)} 件 / 入金_10-11月.csv {len(payments)} 件 / 受注_きれい.csv {len(clean)} 件")


if __name__ == "__main__":
    main()
