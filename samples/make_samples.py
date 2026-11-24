"""見本データ（架空）を作る。

    python samples/make_samples.py

- orders.csv   : 受注データ（Shift_JIS）。表記ゆれやエラーをわざと入れてある
- payments.csv : 入金データ（UTF-8）
名前・メールアドレス・電話番号はすべて架空のもの（メールは example.com）。
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent

PRODUCTS = [
    ("TS-001", "Tシャツ ホワイト M", 2480),
    ("TS-002", "Tシャツ ブラック L", 2480),
    ("MG-010", "マグカップ 350ml", 1650),
    ("BG-101", "トートバッグ キャンバス", 3300),
    ("ST-205", "ステッカー 5枚セット", 550),
    ("CP-300", "キャップ ネイビー", 2980),
]
PAYMENTS = ["クレジットカード", "銀行振込", "コンビニ払い", "代金引換"]
FAMILY = ["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤"]
GIVEN = ["一郎", "花子", "翔太", "美咲", "健太", "由美", "大輔", "さくら", "拓也", "愛"]

HEADER = ["注文番号", "注文日", "顧客名", "メールアドレス", "電話番号", "商品コード", "商品名", "数量", "単価", "合計金額", "支払方法"]


def build_orders(rng: random.Random) -> list[list[str]]:
    rows = []
    start = date(2026, 9, 1)
    for n in range(1, 41):
        code, name, price = rng.choice(PRODUCTS)
        qty = rng.randint(1, 4)
        d = start + timedelta(days=rng.randint(0, 80))
        i = rng.randrange(len(FAMILY))
        rows.append([
            f"ORD-{260000 + n:06d}",
            d.strftime("%Y/%m/%d"),
            f"{FAMILY[i]} {GIVEN[(i + n) % len(GIVEN)]}",
            f"user{n:03d}@example.com",
            f"090-0000-{n:04d}",
            code, name, str(qty), str(price), str(qty * price),
            rng.choice(PAYMENTS),
        ])

    # --- 整形で直る表記ゆれ ---
    rows[1][1] = "2026年9月3日"                  # 日付の書き方
    rows[2][7] = "２"; rows[2][9] = str(2 * int(rows[2][8]))   # 全角数字
    rows[3][9] = f"{int(rows[3][9]):,}円"        # 「1,650円」
    rows[4][0] = "ord-260005"                    # 小文字
    rows[5][4] = "０９０ー００００ー０００６"        # 全角の電話番号
    rows[6][3] = "  USER007@EXAMPLE.COM "        # 大文字・前後の空白
    rows[7][5] = "ｍｇ－０１０"; rows[7][6] = "マグカップ 350ml"; rows[7][8] = "1650"
    rows[7][9] = str(int(rows[7][7]) * 1650)
    rows[8][6] = "ｽﾃｯｶｰ 5枚セット"; rows[8][5] = "ST-205"; rows[8][8] = "550"; rows[8][9] = str(int(rows[8][7]) * 550)

    # --- 検証でエラーになるもの ---
    rows[10][2] = ""                             # 必須の顧客名が空欄
    rows[11][3] = "user012@example"              # メールアドレスの形でない
    rows[12][1] = "2026/02/30"                   # ありえない日付
    rows[13][7] = "0"; rows[13][9] = "0"         # 数量が 1 未満
    rows[14][9] = str(int(rows[14][9]) + 100)    # 合計金額が 数量×単価 と合わない
    rows[15][10] = "PayPay"                      # 使えない支払方法
    rows[16][5] = "XX-9999"                      # 商品コードの書き方が違う
    rows[17][8] = "abc"                          # 単価が数字でない
    rows[18][4] = "12345"                        # 電話番号の形でない

    # --- 重複 ---
    rows.append(list(rows[20]))                  # 注文番号が同じ行（2件目はエラー）
    rows.append(list(rows[21])); rows[-1][2] = rows[21][2] + "（再送）"
    return rows


def build_payments(orders: list[list[str]], rng: random.Random) -> list[list[str]]:
    rows = []
    n = 0
    seen = set()
    for o in orders:
        order_no = o[0].upper()
        if order_no in seen:
            continue
        seen.add(order_no)
        idx = int(order_no[-2:])
        if idx in (25, 30, 35):                  # 入金がまだの注文
            continue
        n += 1
        amount = o[9].replace(",", "").replace("円", "")
        if not amount.isdigit():
            amount = "0"
        if idx == 28:
            amount = str(int(amount) - 500)      # 入金額が足りない
        paid = date(2026, 9, 2) + timedelta(days=rng.randint(0, 85))
        rows.append([f"PAY-{n:05d}", paid.isoformat(), order_no, amount, o[10]])
    rows.append([f"PAY-{n + 1:05d}", "2026-11-20", "ORD-269999", "3300", "銀行振込"])  # 注文の見つからない入金
    return rows


def main() -> None:
    rng = random.Random(20261122)
    orders = build_orders(rng)
    with (HERE / "orders.csv").open("w", encoding="cp932", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(HEADER)
        w.writerows(orders[:30])
        w.writerow([])                                       # 空行（読み飛ばされる）
        w.writerow(orders[30][:-1])                          # 列が1つ足りない行
        w.writerows(orders[31:])
    payments = build_payments(orders, rng)
    with (HERE / "payments.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(["入金ID", "入金日", "注文番号", "入金額", "決済手段"])
        w.writerows(payments)
    print(f"orders.csv: {len(orders)} 行 / payments.csv: {len(payments)} 行")


if __name__ == "__main__":
    main()
