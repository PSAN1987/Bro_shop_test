import os
import json
import time
from datetime import datetime
import pytz

import gspread
from flask import Flask, render_template, render_template_string, request, session, abort
import uuid
from oauth2client.service_account import ServiceAccountCredentials

# 追加 -----------------------------------
import requests
# ----------------------------------------

# line-bot-sdk v2 系
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, PostbackEvent, PostbackAction
)

app = Flask(__name__)
app.secret_key = 'some_secret_key'  # セッションが必要

# -----------------------
# 環境変数取得
# -----------------------
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
SERVICE_ACCOUNT_FILE = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
SPREADSHEET_KEY = os.environ.get("SPREADSHEET_KEY", "")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


# -----------------------
# Google Sheets 接続
# -----------------------
def get_gspread_client():
    """
    環境変数 SERVICE_ACCOUNT_FILE (JSONパス or JSON文字列) から認証情報を取り出し、
    gspread クライアントを返す
    """
    if not SERVICE_ACCOUNT_FILE:
        raise ValueError("環境変数 GCP_SERVICE_ACCOUNT_JSON が設定されていません。")

    service_account_dict = json.loads(SERVICE_ACCOUNT_FILE)

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(service_account_dict, scope)
    return gspread.authorize(credentials)


def get_or_create_worksheet(sheet, title):
    """
    スプレッドシート内で該当titleのワークシートを取得。
    なければ新規作成し、ヘッダを書き込む。
    """
    try:
        ws = sheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=title, rows=2000, cols=50)
        # 必要であればヘッダをセット
        if title == "CatalogRequests":
            ws.update('A1:I1', [[
                "日時",  # ←先頭に日時列
                "氏名", "郵便番号", "住所", "電話番号",
                "メールアドレス", "Insta/TikTok名",
                "在籍予定の学校名と学年", "その他(質問・要望)"
            ]])
        elif title == "簡易見積":
            # 属性カラムを追加したため、A1:M1 で13列に拡張
            ws.update('A1:N1', [[
                "日時", "見積番号", "ユーザーID", "属性",
                "使用日(割引区分)", "予算", "商品名", "枚数",
                "プリント位置", "色数", "背ネーム",
                "合計金額", "単価","WebフォームURL"
            ]])
        elif title == "WebOrderRequests":
            headers = [
    # 基本情報 --------------------------------------------------------
    "日時",
    "商品名", "品番", "カラー番号", "商品カラー",
    "150サイズ枚数", "SSサイズ枚数", "Sサイズ枚数", "Mサイズ枚数",
    "L(F)サイズ枚数", "LL(XL)サイズ枚数", "3L(XXL)サイズ枚数", "合計枚数",

    # ── １ヵ所目 ─────────────────────────────────────────
    "プリント位置No1", "ネーム・番号オプション1", "ネーム・番号プリント種別1",
    "単色カラー1", "フチ付きタイプ1",
    "文字色1", "フチ色1(1)", "フチ色2(1)",
    "フォント種別1", "フォント番号1",
    "プリントカラー1色目(1)", "プリントカラー2色目(1)", "プリントカラー3色目(1)",
    "フルカラーサイズ1",
    "デザイン番号1", "デザインサイズ種別1", "デザイン幅cm1", "デザイン高さcm1",

    # ── ２ヵ所目 ─────────────────────────────────────────
    "プリント位置No2", "ネーム・番号オプション2", "ネーム・番号プリント種別2",
    "単色カラー2", "フチ付きタイプ2",
    "文字色2", "フチ色1(2)", "フチ色2(2)",
    "フォント種別2", "フォント番号2",
    "プリントカラー1色目(2)", "プリントカラー2色目(2)", "プリントカラー3色目(2)",
    "フルカラーサイズ2",
    "デザイン番号2", "デザインサイズ種別2", "デザイン幅cm2", "デザイン高さcm2",

    # ── ３ヵ所目 ─────────────────────────────────────────
    "プリント位置No3", "ネーム・番号オプション3", "ネーム・番号プリント種別3",
    "単色カラー3", "フチ付きタイプ3",
    "文字色3", "フチ色1(3)", "フチ色2(3)",
    "フォント種別3", "フォント番号3",
    "プリントカラー1色目(3)", "プリントカラー2色目(3)", "プリントカラー3色目(3)",
    "フルカラーサイズ3",
    "デザイン番号3", "デザインサイズ種別3", "デザイン幅cm3", "デザイン高さcm3",

    # ── ４ヵ所目 ─────────────────────────────────────────
    "プリント位置No4", "ネーム・番号オプション4", "ネーム・番号プリント種別4",
    "単色カラー4", "フチ付きタイプ4",
    "文字色4", "フチ色1(4)", "フチ色2(4)",
    "フォント種別4", "フォント番号4",
    "プリントカラー1色目(4)", "プリントカラー2色目(4)", "プリントカラー3色目(4)",
    "フルカラーサイズ4",
    "デザイン番号4", "デザインサイズ種別4", "デザイン幅cm4", "デザイン高さcm4",

    # 発送・連絡先など --------------------------------------------------
    "希望お届け日", "使用日", "申込日", "利用学割特典",
    "学校名", "LINE名", "クラス・団体名",
    "郵便番号", "住所1", "住所2", "お届け先宛名", "学校TEL",
    "代表者", "代表者TEL", "代表者メール",
    "デザイン確認方法", "お支払い方法",
    "注文番号", "見積番号", "単価", "合計金額"
]
            # ❶ 必要な列数を確保（あとで行追加時に不足すると困るため）
            ws.resize(rows=2000, cols=len(headers))
            # ❷ A1 だけを指定してヘッダーを書き込む
            ws.update('A1', [headers])
            ws.update('A1', [headers])          # ← 'A1:AZ1' を 'A1' に変更
            ws.resize(rows=2000, cols=len(headers))   # 念のため列も合わせておく
            # 新たに Webフォーム注文のヘッダーをセット（必要に応じて列を追加/変更）
    return ws

# ヘッダーと同じ順序でキーを定義 （フォーム上の name と合わせる）
WEB_ORDER_COLUMN_KEYS = [
    # 基本情報
    "timestamp",
    "productName", "productNo", "colorNo", "colorName",
    "size150", "sizeSS", "sizeS", "sizeM",
    "sizeL", "sizeXL", "sizeXXL", "totalQuantity",

    # ── １ヵ所目 ─────────────────────────────────────────
    "printPositionNo1", "nameNumberOption1", "nameNumberPrintType1",
    "singleColor1", "edgeType1",
    "edgeCustomTextColor1", "edgeCustomEdgeColor1", "edgeCustomEdgeColor2_1",
    "fontType1", "fontNumber1",
    "printColorOption1_1", "printColorOption1_2", "printColorOption1_3",
    "fullColorSize1",
    "designCode1", "designSize1", "designSizeX1", "designSizeY1",

    # ── ２ヵ所目 ─────────────────────────────────────────
    "printPositionNo2", "nameNumberOption2", "nameNumberPrintType2",
    "singleColor2", "edgeType2",
    "edgeCustomTextColor2", "edgeCustomEdgeColor2", "edgeCustomEdgeColor2_2",
    "fontType2", "fontNumber2",
    "printColorOption2_1", "printColorOption2_2", "printColorOption2_3",
    "fullColorSize2",
    "designCode2", "designSize2", "designSizeX2", "designSizeY2",

    # ── ３ヵ所目 ─────────────────────────────────────────
    "printPositionNo3", "nameNumberOption3", "nameNumberPrintType3",
    "singleColor3", "edgeType3",
    "edgeCustomTextColor3", "edgeCustomEdgeColor3", "edgeCustomEdgeColor2_3",
    "fontType3", "fontNumber3",
    "printColorOption3_1", "printColorOption3_2", "printColorOption3_3",
    "fullColorSize3",
    "designCode3", "designSize3", "designSizeX3", "designSizeY3",

    # ── ４ヵ所目 ─────────────────────────────────────────
    "printPositionNo4", "nameNumberOption4", "nameNumberPrintType4",
    "singleColor4", "edgeType4",
    "edgeCustomTextColor4", "edgeCustomEdgeColor4", "edgeCustomEdgeColor2_4",
    "fontType4", "fontNumber4",
    "printColorOption4_1", "printColorOption4_2", "printColorOption4_3",
    "fullColorSize4",
    "designCode4", "designSize4", "designSizeX4", "designSizeY4",

    # 発送・連絡先など
    "deliveryDate", "useDate", "applicationDate", "discountOption",
    "schoolName", "lineName", "classGroupName",
    "zipCode", "address1", "address2","addresseeName","schoolTel",
    "representativeName", "representativeTel", "representativeEmail",
    "designCheckMethod", "paymentMethod",

    "orderNo", "quote_no","unitPrice", "totalPrice"
]

def build_web_order_row_values(data: dict) -> list:
    """
    WebOrderRequests のヘッダー順に沿って、必ず同じ数・同じ順序で配列を返す。
    data にキーが無い場合は空文字 "" を返す。
    """
    row = []
    for key in WEB_ORDER_COLUMN_KEYS:
        row.append(data.get(key, ""))  # 空文字でも埋める
    return row


def write_to_spreadsheet_for_catalog(form_data: dict):
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_KEY)
    worksheet = get_or_create_worksheet(sh, "CatalogRequests")

    # 日本時間の現在時刻
    jst = pytz.timezone('Asia/Tokyo')
    now_jst_str = datetime.now(jst).strftime("%Y/%m/%d %H:%M:%S")

    # address_1 と address_2 を合体して1つのセルに
    full_address = f"{form_data.get('address_1', '')} {form_data.get('address_2', '')}".strip()

    new_row = [
        now_jst_str,  # 先頭に日時
        form_data.get("name", ""),
        form_data.get("postal_code", ""),
        full_address,  # 合体した住所
        form_data.get("phone", ""),
        form_data.get("email", ""),
        form_data.get("sns_account", ""),
        form_data.get("school_grade", ""),
        form_data.get("other", ""),
    ]
    worksheet.append_row(new_row, value_input_option="USER_ENTERED")


# -----------------------
# 簡易見積用データ構造
# -----------------------
from PRICE_TABLE_2025 import (
    PRICE_TABLE_GENERAL,
    PRICE_TABLE_STUDENT
)

from collections import defaultdict

# ▼▼▼ 新規: プリント位置が「前のみ/背中のみ」のときの色数選択肢および対応コスト
COLOR_COST_MAP_SINGLE = {
    "前 or 背中 1色": (0, 0),
    "前 or 背中 2色": (1, 0),
    "前 or 背中 フルカラー": (0, 1)
}

# ▼▼▼ 新規: プリント位置が「前と背中」のときの色数選択肢および対応コスト
COLOR_COST_MAP_BOTH = {
    "前と背中 前1色 背中1色": (0, 0),
    "前と背中 前2色 背中1色": (1, 0),
    "前と背中 前1色 背中2色": (1, 0),
    "前と背中 前2色 背中2色": (2, 0),
    "前と背中 フルカラー": (0, 2)
}

# ユーザの見積フロー管理用（簡易的セッション）
user_estimate_sessions = {}  # { user_id: {"step": n, "answers": {...}, "is_single": bool} }


def write_estimate_to_spreadsheet(user_id, estimate_data, total_price, unit_price):
    """
    計算が終わった見積情報をスプレッドシートの「簡易見積」に書き込む
    """
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_KEY)
    worksheet = get_or_create_worksheet(sh, "簡易見積")

    quote_number = str(int(time.time()))  # 見積番号を UNIX時間 で仮生成
    order_url = f"https://bro-shop-test.onrender.com/web_order_form?quote_no={quote_number}&uid={user_id}"

    # 日本時間の現在時刻
    jst = pytz.timezone('Asia/Tokyo')
    now_jst_str = datetime.now(jst).strftime("%Y/%m/%d %H:%M:%S")

    new_row = [
        now_jst_str,
        quote_number,
        user_id,
        estimate_data['user_type'],  # 追加した「属性」
        f"{estimate_data['usage_date']}({estimate_data['discount_type']})",
        estimate_data.get('budget', ''),
        estimate_data['item'],
        estimate_data['quantity'],
        estimate_data['print_position'],
        estimate_data['color_count'],
        estimate_data.get('back_name', ''), 
       f"¥{unit_price:,}",
       order_url
       ]
    worksheet.append_row(new_row, value_input_option="USER_ENTERED")

    return quote_number


from PRICE_TABLE_2025 import PRICE_TABLE_GENERAL, PRICE_TABLE_STUDENT

def calculate_estimate(estimate_data):
    item = estimate_data.get("item", "")
    pattern_raw = estimate_data.get("pattern", "")
    qty_text_raw = estimate_data.get("quantity", "")
    user_type = estimate_data.get("user_type", "一般")

    # ▼ パターン表記（パターンA → A）に変換
    pattern = pattern_raw.replace("パターン", "").strip()

    # ▼ 数量レンジの波ダッシュ表記に統一（～ → 〜）
    qty_text = qty_text_raw.replace("～", "〜").strip()

    # ▼ 数値換算マップ
    quantity_map = {
        "10〜19枚": 10, "20〜29枚": 20, "30〜39枚": 30,
        "40〜49枚": 40, "50〜99枚": 50, "100枚以上": 100
    }

    quantity_value = quantity_map.get(qty_text, 1)

    def get_quantity_range(qty):
        if qty < 20:
            return "10〜19枚"
        elif qty < 30:
            return "20〜29枚"
        elif qty < 40:
            return "30〜39枚"
        elif qty < 50:
            return "40〜49枚"
        elif qty < 100:
            return "50〜99枚"
        else:
            return "100枚以上"

    quantity_range = get_quantity_range(quantity_value)

    # ▼ 属性ごとにテーブル選択
    price_table = PRICE_TABLE_STUDENT if user_type == "学生" else PRICE_TABLE_GENERAL

    for row in price_table:
        if row["item"] == item and row["pattern"] == pattern and row["quantity_range"] == quantity_range:
            unit_price = row["unit_price"]
            total_price = unit_price * quantity_value
            return total_price, unit_price

    # 見つからない場合
    return 0, 0


# -----------------------
# ここからFlex Message定義
# -----------------------
def flex_user_type():
    flex_body = {
        "type": "bubble",
        "hero": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "❶属性",
                    "weight": "bold",
                    "size": "lg",
                    "align": "center"
                },
                {
                    "type": "text",
                    "text": "ご利用者の属性を選択してください。",
                    "size": "sm",
                    "wrap": True
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#000000",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "学生",
                        "text": "学生"
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#000000",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "一般",
                        "text": "一般"
                    }
                }
            ],
            "flex": 0
        }
    }
    return FlexSendMessage(alt_text="属性を選択してください", contents=flex_body)


def flex_usage_date():
    flex_body = {
        "type": "bubble",
        "hero": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "❷使用日",
                    "weight": "bold",
                    "size": "lg",
                    "align": "center"
                },
                {
                    "type": "text",
                    "text": "ご使用日は、今日より? \n(注文日より使用日が14日目以降なら早割)",
                    "size": "sm",
                    "wrap": True
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#000000",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "14日目以降",
                        "text": "14日目以降"
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#000000",
                    "height": "sm",
                    "action": {
                        "type": "message",
                        "label": "14日目以内",
                        "text": "14日目以内"
                    }
                }
            ],
            "flex": 0
        }
    }
    return FlexSendMessage(alt_text="使用日を選択してください", contents=flex_body)

def flex_item_select():
    def create_category_bubble(title, items):
        return {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {"type": "text", "text": f"③商品カテゴリー：{title}", "weight": "bold", "size": "lg", "align": "center"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "spacing": "sm",
                                "contents": [
                                    *[{
                                        "type": "image",
                                        "url": url,
                                        "size": "sm",
                                        "aspectMode": "cover",
                                        "aspectRatio": "1:1",
                                        "action": {
                                            "type": "message",
                                            "label": label,
                                            "text": label
                                        }
                                    } for label, url in items[:2]]
                                ]
                            },
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "spacing": "sm",
                                "contents": [
                                    *[{
                                        "type": "image",
                                        "url": url,
                                        "size": "sm",
                                        "aspectMode": "cover",
                                        "aspectRatio": "1:1",
                                        "action": {
                                            "type": "message",
                                            "label": label,
                                            "text": label
                                        }
                                    } for label, url in items[2:]]
                                ]
                            }
                        ]
                    }
                ]
            }
        }

    # 画像付きアイテムカテゴリ一覧
    categories = [
        ("Tシャツ系", [
            ("ドライTシャツ", "https://catalog-bot-zf1t.onrender.com/dry_tshirt.png"),
            ("ハイクオリティーTシャツ", "https://catalog-bot-zf1t.onrender.com/high_quality_tshirt.png"),
            ("ドライロングTシャツ", "https://catalog-bot-zf1t.onrender.com/dry_long_tshirt.png"),
            ("ドライポロシャツ", "https://catalog-bot-zf1t.onrender.com/dry_polo.png")
        ]),
        ("スポーツユニフォーム系", [
            ("ゲームシャツ", "https://catalog-bot-zf1t.onrender.com/game_shirt.png"),
            ("ベースボールシャツ", "https://catalog-bot-zf1t.onrender.com/baseball_shirt.png"),
            ("ストライプベースボールシャツ", "https://catalog-bot-zf1t.onrender.com/stripe_baseball.png"),
            ("ストライプユニフォーム", "https://catalog-bot-zf1t.onrender.com/stripe_uniform.png")
        ]),
        ("トレーナー・バスケ系", [
            ("クールネックライトトレーナー", "https://catalog-bot-zf1t.onrender.com/crew_trainer.png"),
            ("ジップアップライトトレーナー", "https://catalog-bot-zf1t.onrender.com/zip_trainer.png"),
            ("フーディーライトトレーナー", "https://catalog-bot-zf1t.onrender.com/hoodie_trainer.png"),
            ("バスケシャツ", "https://catalog-bot-zf1t.onrender.com/basketball_shirt.png")
        ])
    ]

    # 各カテゴリごとのBubble生成
    bubbles = [create_category_bubble(title, items) for title, items in categories]

    return FlexSendMessage(
        alt_text="商品カテゴリーを選択してください",
        contents={
            "type": "carousel",
            "contents": bubbles
        }
    )

def flex_pattern_select(product_name):
    patterns = ["A", "B", "C", "D", "E", "F"]
    bubbles = []

    for p in patterns:
        bubbles.append({
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": f"https://catalog-bot-zf1t.onrender.com/{product_name}_{p}.png",  # 実際の画像URLに差し替えてください
                "size": "full",
                "aspectMode": "cover",
                "aspectRatio": "1:1"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": f"パターン{p}で金額を確認",
                        "wrap": True,
                        "weight": "bold",
                        "align": "center"
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#000000",
                        "action": {
                            "type": "message",
                            "label": f"パターン{p}",
                            "text": f"パターン{p}"
                        }
                    }
                ]
            }
        })

    return FlexSendMessage(
        alt_text="パターンを選択してください",
        contents={
            "type": "carousel",
            "contents": bubbles
        }
    )


def flex_quantity():
    quantities = ["10～19枚", "20～29枚", "30～39枚", "40～49枚", "50～99枚", "100枚以上"]
    buttons = []
    for q in quantities:
        buttons.append({
            "type": "button",
            "style": "primary",
            "color": "#000000",
            "height": "sm",
            "action": {
                "type": "message",
                "label": q,
                "text": q
            }
        })

    flex_body = {
        "type": "bubble",
        "hero": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "❺枚数",
                    "weight": "bold",
                    "size": "lg",
                    "align": "center"
                },
                {
                    "type": "text",
                    "text": "必要枚数を選択してください。",
                    "size": "sm",
                    "wrap": True
                },
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": buttons
        }
    }
    return FlexSendMessage(alt_text="必要枚数を選択してください", contents=flex_body)

def flex_estimate_result_with_image(estimate_data, total_price, unit_price, quote_number):
    item = estimate_data["item"]
    pattern_raw = estimate_data.get("pattern", "")
    pattern = pattern_raw.replace("パターン", "").strip()  # A, B, C...

    image_url = f"https://catalog-bot-zf1t.onrender.com/{item}_{pattern}.png"

    alt_text = f"{item}の見積結果"

    flex = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": image_url,
            "size": "full",
            "aspectMode": "cover",
            "aspectRatio": "1:1"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": f"✅ 概算見積", "weight": "bold", "size": "lg"},
                {"type": "text", "text": f"属性: {estimate_data['user_type']}"},
                {"type": "text", "text": f"使用日: {estimate_data['usage_date']}（{estimate_data['discount_type']}）"},
                {"type": "text", "text": f"商品: {item}"},
                {"type": "text", "text": f"パターン: {pattern_raw}"},
                {"type": "text", "text": f"枚数: {estimate_data['quantity']}"},
                {"type": "separator"},
                {"type": "text", "text": f"【合計金額】¥{total_price:,}", "weight": "bold"},
                {"type": "text", "text": f"【1枚あたり】¥{unit_price:,}"},
                {"type": "separator"},
                {"type": "text", "text": "※上記は色数1色・背ネームなしの簡易見積です。\nより正確な金額をご希望の方は、下記からデザイン相談へお進みください。", "wrap": True, "size": "sm"}
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#000000",
                    "action": {
                        "type": "postback",
                        "label": "デザイン相談",
                        "data": "CONSULT_DESIGN"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "個別相談",
                        "data": "CONSULT_PERSONAL"
                    }
                }
            ]
        }
    }

    return FlexSendMessage(alt_text=alt_text, contents=flex)

# -----------------------
# お問い合わせ時に返信するFlex Message
# -----------------------
def flex_inquiry():
    contents = {
        "type": "carousel",
        "contents": [
            # 1個目: FAQ
            {
                "type": "bubble",
                "hero": {
                    "type": "image",
                    "url": "https://catalog-bot-zf1t.onrender.com/IMG_5765.PNG",
                    "size": "full",
                    "aspectRatio": "501:556",
                    "aspectMode": "cover",
                    "action": {
                        "type": "uri",
                        "uri": "https://graffitees.jp/faq/"
                    }
                }
            },
            # 2個目: 有人チャット
            {
                "type": "bubble",
                "hero": {
                    "type": "image",
                    "url": "https://catalog-bot-zf1t.onrender.com/IMG_5766.PNG",
                    "size": "full",
                    "aspectRatio": "501:556",
                    "aspectMode": "cover",
                    "action": {
                        "type": "message",
                        "text": "#有人チャット"
                    }
                }
            },
        ]
    }
    return FlexSendMessage(alt_text="お問い合わせ情報", contents=contents)


# -----------------------
# デザイン相談に誘導するFlex Message
# -----------------------

def flex_consultation_options():
    flex = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "ご希望の相談方法をお選びください",
                    "wrap": True,
                    "weight": "bold",
                    "size": "md"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#000000",
                    "action": {
                        "type": "postback",
                        "label": "デザイン相談",
                        "data": "CONSULT_DESIGN"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "個別相談",
                        "data": "CONSULT_PERSONAL"
                    }
                }
            ]
        }
    }
    return FlexSendMessage(alt_text="相談方法を選択してください", contents=flex)


# -----------------------
# 0) ハンドラ側でキャッチして動的 URL を返す
# -----------------------
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data or ""

    # --- デザイン相談 or 個別相談 選択時の応答 ---------------
    if data == "CONSULT_DESIGN":
        message = (
            "有人チャットに接続いたします。\n"
            "ご検討中のデザインがございましたら、画像やイラストなどの資料をお送りくださいませ。\n\n"
            "※当ショップの営業時間は【10:00～19:00】でございます。\n"
            "営業時間外にいただいたお問い合わせにつきましては、確認でき次第、順次ご対応させていただきます。\n"
            "何卒ご理解賜りますようお願い申し上げます。\n\n"
            "その他ご要望やご不明点がございましたら、お気軽にメッセージをお送りくださいませ。\n"
            "どうぞよろしくお願いいたします。"
        )
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=message)
        )
        return

    if data == "CONSULT_PERSONAL":
        message = (
            "スタッフによるチャット対応を開始いたします。\n"
            "ご検討中の商品について、金額やデザインに関するご質問がございましたら、こちらからお気軽にご相談ください。\n\n"
            "※当ショップの営業時間は【10:00～19:00】です。\n"
            "営業時間外にいただいたお問い合わせにつきましては、確認でき次第、順次ご対応させていただきます。\n"
            "あらかじめご了承くださいませ。\n\n"
            "そのほか、ご要望やご不明点がございましたら、メッセージにてお知らせください。\n"
            "よろしくお願いいたします。"
        )
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=message)
        )
        return
    
    # --- 注文確定 --------------------------------------------------
    if data.startswith("CONFIRM_ORDER:"):
        order_no = data.split(":",1)[1]
        ok = mark_order_confirmed(order_no)          # ← 次で定義
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"注文番号 {order_no} を確定しました！担当スタッフから追って納期などの詳細をご連絡します。")
        )
        return

    # --- 今は注文しない -------------------------------------------
    if data.startswith("CANCEL_ORDER:"):
        order_no = data.split(":",1)[1]
        ok = mark_order_confirmed(order_no, cancel=True) 
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="ご注文は保留のままとなりました。別の商品にて再検討される場合はカンタン見積もしくはWEBフォームから再開してください。")
        )
        return
    
    if event.postback.data == "WEB_ORDER":
        uid  = event.source.user_id
        url  = f"https://bro-shop-test.onrender.com/web_order_form?uid={uid}"

        flex = {
            "type": "bubble",
            # バブルの背景はデフォルト（白）のまま
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "16px",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": "WEBフォームでの注文を開く",
                        "weight": "bold",
                        "size": "lg",
                        "align": "center",
                        "wrap": True,
                        "color": "#000000"          # 見出しテキストは黒
                    },
                    {
                        "type": "button",
                        "style": "primary",          # primary にすると文字は自動で白
                        "color": "#000000",          # ボタン背景をピンク
                        "height": "sm",
                        "action": {
                            "type": "uri",
                            "label": "開く",
                            "uri": url
                        }
                    }
                ]
            }
        }

        line_bot_api.reply_message(
            event.reply_token,
            FlexSendMessage(alt_text="WEBフォーム", contents=flex)
        )


# -----------------------
# 1) LINE Messaging API 受信 (Webhook)
# -----------------------
@app.route("/line/callback", methods=["POST"])
def line_callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400, "Invalid signature. Please check your channel access token/channel secret.")

    return "OK", 200

# -----------------------
# 2) LINE上でメッセージ受信時
# -----------------------
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event: MessageEvent):
    user_id = event.source.user_id
    user_message = event.message.text.strip()

    # 1) お問い合わせ対応
    if user_message == "お問い合わせ":
        line_bot_api.reply_message(
            event.reply_token,
            flex_inquiry()
        )
        return

    # 2) 有人チャット
    if user_message == "#有人チャット":
        reply_text = (
            "有人チャットに接続いたします。\n"
            "ご検討中のデザインを画像やイラストでお送りください。\n\n"
            "※当ショップの営業時間は10：00～18：00となります。\n"
            "営業時間外のお問い合わせにつきましては確認ができ次第の回答となります。\n"
            "誠に恐れ入りますが、ご了承くださいませ。\n\n"
            "その他ご要望などがございましたらメッセージでお送りくださいませ。\n"
            "よろしくお願い致します。"
        )
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        return

    # すでに見積りフロー中かどうか
    if user_id in user_estimate_sessions and user_estimate_sessions[user_id]["step"] > 0:
        process_estimate_flow(event, user_message)
        return

    # 見積りフロー開始
    if user_message == "カンタン見積り":
        start_estimate_flow(event)
        return

    # カタログ案内
    if "キャンペーン" in user_message or "catalog" in user_message.lower():
        send_catalog_info(event)
        return

    # その他のメッセージはスルー
    return


def send_catalog_info(event: MessageEvent):
    reply_text = (
        "🎁➖➖➖➖➖➖➖➖🎁\n"
        "  ✨カタログ無料プレゼント✨\n"
        "🎁➖➖➖➖➖➖➖➖🎁\n\n"
        "クラスTシャツの最新デザインやトレンド情報が詰まったカタログを、"
        "期間限定で無料でお届けします✨\n\n"
        "【応募方法】\n"
        "以下のアカウントをフォロー👇\n"
        "（どちらかでOK🙆）\n"
        "📸 Instagram\n"
        "https://www.instagram.com/graffitees_045/\n"
        "🎥 TikTok\n"
        "https://www.tiktok.com/@graffitees_045\n\n"
        "フォロー後、下記のフォームからお申込みください👇\n"
        "📩 カタログ申込みフォーム\n"
        "https://bro-shop-test.onrender.com/catalog_form\n"
        "⚠️ 注意：サブアカウントや重複申込みはご遠慮ください。\n\n"
        "【カタログ発送時期】\n"
        "📅 2025年4月中旬より郵送で発送予定です。\n\n"
        "【配布数について】\n"
        "先着300名様分を予定しています。\n"
        "※応募多数となった場合、配布数の増加や抽選となる可能性があります。\n\n"
        "ご応募お待ちしております🙆"
    )
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )


# -----------------------
# 見積りフロー
# -----------------------
def start_estimate_flow(event: MessageEvent):
    user_id = event.source.user_id
    user_estimate_sessions[user_id] = {
        "step": 1,
        "answers": {},
        "is_single": False
    }

    line_bot_api.reply_message(
        event.reply_token,
        flex_user_type()
    )


def process_estimate_flow(event: MessageEvent, user_message: str):
    user_id = event.source.user_id
    if user_id not in user_estimate_sessions:
        return

    session_data = user_estimate_sessions[user_id]
    step = session_data["step"]

    if step == 1:
        if user_message in ["学生", "一般"]:
            session_data["answers"]["user_type"] = user_message
            session_data["step"] = 2
            line_bot_api.reply_message(event.reply_token, flex_usage_date())
        else:
            del user_estimate_sessions[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="入力内容に誤りがあります。もう一度「カンタン見積り」からやり直してください。"))
        return

    elif step == 2:
        if user_message in ["14日目以降", "14日目以内"]:
            session_data["answers"]["usage_date"] = user_message
            session_data["answers"]["discount_type"] = "早割" if user_message == "14日目以降" else "通常"
            session_data["step"] = 3
            line_bot_api.reply_message(event.reply_token, flex_item_select())
        else:
            del user_estimate_sessions[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="入力内容に誤りがあります。もう一度「カンタン見積り」からやり直してください。"))
        return

    elif step == 3:
        valid_products = [
            "ドライTシャツ", "ハイクオリティーTシャツ", "ドライロングTシャツ", "ドライポロシャツ",
            "ゲームシャツ", "ベースボールシャツ", "ストライプベースボールシャツ", "ストライプユニフォーム",
            "クールネックライトトレーナー", "ジップアップライトトレーナー", "フーディーライトトレーナー", "バスケシャツ"
        ]
        if user_message in valid_products:
            session_data["answers"]["item"] = user_message
            session_data["step"] = 4
            line_bot_api.reply_message(event.reply_token, flex_pattern_select(user_message))
        else:
            del user_estimate_sessions[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="入力内容に誤りがあります。もう一度「カンタン見積り」からやり直してください。"))
        return

    elif step == 4:
        valid_patterns = ["パターンA", "パターンB", "パターンC", "パターンD", "パターンE", "パターンF"]
        if user_message in valid_patterns:
            session_data["answers"]["pattern"] = user_message
            session_data["step"] = 5
            line_bot_api.reply_message(event.reply_token, flex_quantity())
        else:
            del user_estimate_sessions[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="入力内容に誤りがあります。もう一度「カンタン見積り」からやり直してください。"))
        return

    elif step == 5:
        valid_choices = ["10～19枚", "20～29枚", "30～39枚", "40～49枚", "50～99枚", "100枚以上"]
        if user_message in valid_choices:
            session_data["answers"]["quantity"] = user_message
            session_data["step"] = 6  # 最終ステップに進む

            # プリント位置、色数、背ネームは仮値を自動設定
            session_data["answers"]["print_position"] = "前のみ"
            session_data["answers"]["color_count"] = "前 or 背中 1色"  # COLOR_COST_MAP_SINGLE より
            session_data["answers"]["back_name"] = ""

            # 見積もりを実行
            est_data = session_data["answers"]
            total_price, unit_price = calculate_estimate(est_data)
            quote_number = write_estimate_to_spreadsheet(user_id, est_data, total_price, unit_price)

            # Flex メッセージ（画像付き見積結果）
            flex_msg = flex_estimate_result_with_image(est_data, total_price, unit_price, quote_number)

            line_bot_api.reply_message(
                event.reply_token,
                flex_msg
            )

            # セッション削除
            del user_estimate_sessions[user_id]

    else:
        del user_estimate_sessions[user_id]
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="入力内容に誤りがあります。もう一度「カンタン見積り」からやり直してください。")
        )
    return



# -----------------------
# 3) カタログ申し込みフォーム表示 (GET)
# -----------------------
@app.route("/catalog_form", methods=["GET"])
def show_catalog_form():
    token = str(uuid.uuid4())
    session['catalog_form_token'] = token

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>カタログ申込フォーム</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: sans-serif;
        }}
        .container {{
            max-width: 600px; 
            margin: 0 auto;
            padding: 1em;
        }}
        label {{
            display: block;
            margin-bottom: 0.5em;
        }}
        input[type=text], input[type=email], textarea {{
            width: 100%;
            padding: 0.5em;
            margin-top: 0.3em;
            box-sizing: border-box;
        }}
        input[type=submit] {{
            padding: 0.7em 1em;
            font-size: 1em;
            margin-top: 1em;
        }}
    </style>
    <script>
    async function fetchAddress() {{
        let pcRaw = document.getElementById('postal_code').value.trim();
        pcRaw = pcRaw.replace('-', '');
        if (pcRaw.length < 7) {{
            return;
        }}
        try {{
            const response = await fetch(`https://api.zipaddress.net/?zipcode=${{pcRaw}}`);
            const data = await response.json();
            if (data.code === 200) {{
                // 都道府県・市区町村 部分だけを address_1 に自動入力
                document.getElementById('address_1').value = data.data.fullAddress;
            }}
        }} catch (error) {{
            console.log("住所検索失敗:", error);
        }}
    }}
    </script>
</head>
<body>
    <div class="container">
      <h1>カタログ申込フォーム</h1>
      <p>以下の項目をご記入の上、送信してください。</p>
      <form action="/submit_form" method="post">
          <!-- ワンタイムトークン -->
          <input type="hidden" name="form_token" value="{token}">

          <label>氏名（必須）:
              <input type="text" name="name" required>
          </label>

          <label>郵便番号（必須）:<br>
              <small>※自動で住所補完します。(ブラウザの場合)</small><br>
              <input type="text" name="postal_code" id="postal_code" onkeyup="fetchAddress()" required>
          </label>

          <label>都道府県・市区町村（必須）:<br>
              <small>※郵便番号入力後に自動補完されます。修正が必要な場合は上書きしてください。</small><br>
              <input type="text" name="address_1" id="address_1" required>
          </label>

          <label>番地・部屋番号など（必須）:<br>
              <small>※カタログ送付のために番地や部屋番号を含めた完全な住所の記入が必要です</small><br>
              <input type="text" name="address_2" id="address_2" required>
          </label>

          <label>電話番号（必須）:
              <input type="text" name="phone" required>
          </label>

          <label>メールアドレス（必須）:
              <input type="email" name="email" required>
          </label>

          <label>Insta・TikTok名（必須）:
              <input type="text" name="sns_account" required>
          </label>

          <label>2025年度に在籍予定の学校名と学年（未記入可）:
              <input type="text" name="school_grade">
          </label>

          <label>その他（質問やご要望など）:
              <textarea name="other" rows="4"></textarea>
          </label>

          <input type="submit" value="送信">
      </form>
    </div>
</body>
</html>
"""
    return render_template_string(html_content)


# -----------------------
# 4) カタログ申し込みフォームの送信処理
# -----------------------
@app.route("/submit_form", methods=["POST"])
def submit_catalog_form():
    form_token = request.form.get('form_token')
    if form_token != session.get('catalog_form_token'):
        return "二重送信、あるいは不正なリクエストです。", 400

    session.pop('catalog_form_token', None)

    form_data = {
        "name": request.form.get("name", "").strip(),
        "postal_code": request.form.get("postal_code", "").strip(),
        "address_1": request.form.get("address_1", "").strip(),
        "address_2": request.form.get("address_2", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "email": request.form.get("email", "").strip(),
        "sns_account": request.form.get("sns_account", "").strip(),
        "school_grade": request.form.get("school_grade", "").strip(),
        "other": request.form.get("other", "").strip(),
    }

    try:
        write_to_spreadsheet_for_catalog(form_data)
    except Exception as e:
        return f"エラーが発生しました: {e}", 500

    return "フォーム送信ありがとうございました！ カタログ送付をお待ちください。", 200


# ========== ここから新規追加 (Webオーダーフォーム) ==========

@app.route("/web_order_form")
def show_web_order_form():
    quote_no = request.args.get("quote_no")
    uid = request.args.get("uid")
    initial_data = {}

    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_KEY)

    # ▼ ① WebOrderRequests から最新の下書きデータを探す
    try:
        ws_order = get_or_create_worksheet(sh, "WebOrderRequests")
        quote_col = ws_order.col_values(WEB_ORDER_COLUMN_KEYS.index("quote_no") + 1)
        if quote_no in quote_col:
            idx = quote_col.index(quote_no) + 1
            row = ws_order.row_values(idx)
            initial_data = dict(zip(WEB_ORDER_COLUMN_KEYS, row))
    except Exception as e:
        print(f"WebOrderRequests から取得失敗: {e}")

    # ▼ ② もし WebOrderRequests になければ簡易見積から fallback する（任意）
    if not initial_data and quote_no:
        try:
            ws_estimate = get_or_create_worksheet(sh, "簡易見積")
            estimate_col = ws_estimate.col_values(1)  # 見積番号列
            if quote_no in estimate_col:
                idx = estimate_col.index(quote_no) + 1
                row = ws_estimate.row_values(idx)
                initial_data = {
                    "productName": row[6],
                    "quantity": row[7],
                    "print_position": row[8],
                    "color_count": row[9],
                    "back_name": row[10],
                }
        except Exception as e:
            print(f"簡易見積からの読み込みも失敗: {e}")

    # ▼ render_template に渡す
    return render_template(
        "web_order_form.html",
        token=str(uuid.uuid4()),
        liff_id=os.getenv("WEB_ORDER_LIFF_ID"),
        initial_data=initial_data,
        quote_no=quote_no
    )


@app.route("/submit_web_order_form", methods=["POST"])
@app.route("/submit_web_order_form", methods=["POST"])
def submit_web_order_form():
    form_data = {k: request.form.get(k, "").strip() for k in request.form}
    submit_mode = request.form.get("submit_mode", "final")  # default = final

    # --- ✅ 注文番号の扱い（初回だけ生成） ---
    order_no = form_data.get("orderNo")
    if not order_no:
        jst = pytz.timezone('Asia/Tokyo')
        order_no = datetime.now(jst).strftime("%Y%m%d%H%M%S")
    form_data["orderNo"] = order_no

    # --- ✅ タイムスタンプとステータスの保存 ---
    jst = pytz.timezone('Asia/Tokyo')
    now_jst_str = datetime.now(jst).strftime("%Y/%m/%d %H:%M:%S")
    form_data["timestamp"] = now_jst_str
    form_data["submit_mode"] = submit_mode  # ← 下書き or 確定ステータス保持

    # --- ✅ バリデーション（確定時のみ） ---
    if submit_mode == "final":
        required_fields = [
            "productName", "colorName", "sizeM", "deliveryDate",
            "schoolName", "representativeName", "representativeTel",
            "zipCode", "address2", "addresseeName", "discountOption",
            "designCheckMethod", "paymentMethod"
        ]
        for field in required_fields:
            if not form_data.get(field):
                return f"必須項目が未入力です：{field}", 400

    # --- ✅ 金額再計算（常に実行） ---
    est = calculate_web_order_estimate(form_data)
    form_data["unitPrice"] = est["unit_price"]
    form_data["totalPrice"] = est["total_price"]

    # --- ✅ スプレッドシート保存（新規 or 上書き） ---
    write_to_spreadsheet_for_web_order(form_data)

    # --- ✅ 通知（注文確定時のみ） ---
    if submit_mode == "final":
        uid = form_data.get("lineUserId")
        if uid:
            summary = make_order_summary(order_no, form_data, est)
            flex_msg = build_order_confirm_flex(order_no, summary)
            line_bot_api.push_message(uid, flex_msg)

    # --- ✅ レスポンス返却 ---
    return "保存が完了しました。" if submit_mode == "draft" else "注文を受け付けました！", 200


def write_to_spreadsheet_for_web_order(data: dict):
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_KEY)
    worksheet = get_or_create_worksheet(sh, "WebOrderRequests")

    # row_values をヘッダー順に作成
    row_values = build_web_order_row_values(data)

    # 書き込む
    worksheet.append_row(row_values, value_input_option="USER_ENTERED")

    
def calculate_web_order_estimate(data: dict) -> dict:
    """Web オーダーフォーム１件ぶんの単価・合計金額を返す"""

    # 1) 基本行を PRICE_TABLE から取得 ------------------------------
    item          = data.get("productName", "")
    qty           = int(data.get("totalQuantity", "0") or 0)
    discount_type = "早割" if data.get("discountOption") == "早割" else "通常"

    # プリント位置数 (printPositionNo1〜4 に値が入っている数)
    pos_cnt = sum(1 for i in range(1,5) if data.get(f"printPositionNo{i}"))

    # PRICE_TABLE から該当行検索
    def _find():
        for row in PRICE_TABLE:
            if (row["item"] == item 
                and row["discount_type"] == discount_type 
                and row["min_qty"] <= qty <= row["max_qty"]):
                return row
        return None

    row = _find()
    if not row:
        # 見つからない場合は金額0を返すなど、適宜処理
        return {
            "unit_price": 0,
            "total_price": 0,
            "base_unit": 0,
            "pos_add_fee": 0,
            "color_fee": 0,
            "back_name_fee": 0,
            "option_ink_extra": 0,
            "fullcolor_extra": 0,
            "qty": qty
        }

    base_unit   = row["unit_price"]
    pos_add_fee = row["pos_add"] * max(0, pos_cnt-1)

    # 2) プリントカラー追加料金 ------------------------------
    color_add_cnt    = 0     # 2色なら+1、3色なら+2
    option_ink_extra = 0
    fullcolor_extra  = 0
    back_name_fee    = 0     # 背ネーム・番号セット等の加算
    # ↑ 従来の背ネーム類はここへ合算していく

    for p in range(1,5):
        if not data.get(f"printPositionNo{p}"):
            continue

        # 1〜3色入力欄(プリントカラー・オプション)で実際に入力された値を取得
        color_list = [
            data.get(f"printColorOption{p}_1"),
            data.get(f"printColorOption{p}_2"),
            data.get(f"printColorOption{p}_3"),
        ]
        color_list = [c for c in color_list if c]  # 空文字除外

        # 2色指定なら +1、3色指定なら +2
        if len(color_list) == 2:
            color_add_cnt += 1
        elif len(color_list) == 3:
            color_add_cnt += 2

        # 各色の属性チェック
        for c in color_list:
            # (A) ネーム＆背番号セット/ネーム(大)/(小)/番号(大)/(小) が含まれていたら back_name_fee
            if c in BACK_NAME_FEE:  
                back_name_fee += BACK_NAME_FEE[c]

            # (B) 特殊カラー(グリッター等)があれば SPECIAL_SINGLE_COLOR_FEE
            if c in SPECIAL_SINGLE_COLOR_FEE:
                back_name_fee += SPECIAL_SINGLE_COLOR_FEE[c]

            # (C) COLOR_ATTR_MAP で "オプションインク" なら、option_ink_extra を加算
            if COLOR_ATTR_MAP.get(c) == "オプションインク":
                option_ink_extra += OPTION_INK_EXTRA

        # フルカラーオプション
        fcs = data.get(f"fullColorSize{p}")  # "S"/"M"/"L" など
        if fcs:
            fullcolor_extra += FULLCOLOR_SIZE_FEE.get(fcs, 0)  # サイズ別に加算

        # 3) ネーム&番号カラーオプション（単色 or フチ付き）----------------
        # 単色カラーを選択していた場合
        single_color = data.get(f"singleColor{p}")
        if single_color and single_color in SPECIAL_SINGLE_COLOR_FEE:
            back_name_fee += SPECIAL_SINGLE_COLOR_FEE[single_color]

        # フチ付きタイプを選択していた場合
        edge_type = data.get(f"edgeType{p}")
        if edge_type and edge_type != "なし":
            # たとえばフチ付きは +100円
            back_name_fee += 100

            # カスタムフチ色の場合、edgeCustomTextColor{p} / edgeCustomEdgeColor{p} / edgeCustomEdgeColor2_{p} の中に
            # 特殊色があれば追加
            edge_text = data.get(f"edgeCustomTextColor{p}")
            edge_col1 = data.get(f"edgeCustomEdgeColor{p}")
            edge_col2 = data.get(f"edgeCustomEdgeColor2_{p}")

            for ec in (edge_text, edge_col1, edge_col2):
                if ec and ec in SPECIAL_SINGLE_COLOR_FEE:
                    back_name_fee += SPECIAL_SINGLE_COLOR_FEE[ec]

    # カラー追加料金 (各1色目はベース料金に含まれている想定)
    # color_add_cnt * row["color_add"] で追加料金
    color_fee = color_add_cnt * row["color_add"] + fullcolor_extra + option_ink_extra

    # 4) 単価・合計 ---------------------------------
    unit_price  = base_unit + pos_add_fee + color_fee + back_name_fee
    total_price = unit_price * qty

    return {
        "unit_price":       unit_price,
        "total_price":      total_price,
        "base_unit":        base_unit,
        "pos_add_fee":      pos_add_fee,
        "color_fee":        color_fee,
        "back_name_fee":    back_name_fee,
        "option_ink_extra": option_ink_extra,
        "fullcolor_extra":  fullcolor_extra,
        "qty":              qty
    }

def make_order_summary(order_no: str,
                       data: dict,
                       est: dict) -> str:
    """LINE に送るサマリー（日本語レイアウト & 価格内訳）"""

    # サイズ別内訳（0 枚は表示しない）
    size_map = [("150","size150"),("SS","sizeSS"),("S","sizeS"),
                ("M","sizeM"),("L(F)","sizeL"),("LL(XL)","sizeXL"),
                ("3L","sizeXXL")]
    size_lines = [f"{label}:{data.get(key,0)}枚" for label,key in size_map]
    size_block = ", ".join(size_lines)

    # プリント位置＋色
    pos_lines = []
    for p in range(1,5):
        if not data.get(f"printPositionNo{p}"):
            continue
        cols = [data.get(f"printColorOption{p}_{i}") for i in (1,2,3)]
        cols = ", ".join([c for c in cols if c])
        pos_lines.append(f"{p}か所目 ({data.get(f'printPositionNo{p}')}) : {cols}")
    pos_block = "\n".join(pos_lines) if pos_lines else "—"

    # （背ネーム・番号などを取得する変数 back_name があっても、ここでは表示しないので削除またはコメントアウト）

    # 価格内訳
    price_break_down = (
        f"  ベース価格          ¥{est['base_unit']:,}\n"
        f"  位置追加            +¥{est['pos_add_fee']:,}\n"
        f"  色追加              +¥{est['color_fee']:,}\n"
        f"  背ネーム・番号      +¥{est['back_name_fee']:,}\n"
        "  -------------------------------\n"
        f"  単価               ¥{est['unit_price']:,}\n"
        f"  合計（{est['qty']}枚）   ¥{est['total_price']:,}"
    )

    # メッセージ作成
    return (
        "ご注文ありがとうございます。\n\n"
        f"注文番号: {order_no}\n"
        f"商品: {data.get('productName')}\n"
        f"商品カラー: {data.get('colorName')}\n"
        f"サイズ別枚数: {size_block}\n"
        f"合計枚数: {est['qty']} 枚\n\n"
        "【プリントカラー】\n"
        f"{pos_block}\n\n"
        # ↓ この2行を削除・コメントアウトしておく
        # "【番号・ネーム情報】\n"
        # f"{back_name}\n\n"
        "【価格内訳（1枚あたり）】\n"
        f"{price_break_down}\n\n"
        "※納期は注文確定後に担当スタッフから連絡をします。"
    )

def build_order_confirm_flex(order_no: str,
                             summary_text: str) -> FlexSendMessage:
    """
    - order_no      … make_order_summary() で使った注文番号
    - summary_text  … make_order_summary() で生成した全文
                      （2000 文字以内ならそのまま入れて OK）
    """
    bubble = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    # ▼ wrap=True を必ず付けると長文でも折り返してくれます
                    "type": "text",
                    "text": summary_text,
                    "wrap": True,
                    "size": "sm",
                    "color": "#000000"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#000000",          # ピンク
                    "action": {
                        "type": "postback",
                        "label": "注文確定",
                        "data": f"CONFIRM_ORDER:{order_no}"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "今は注文しない",
                        "data": f"CANCEL_ORDER:{order_no}"
                    }
                }
            ]
        }
    }

    # FlexSendMessage に詰めて返す
    return FlexSendMessage(
        alt_text="ご注文内容の確認",
        contents=bubble
    )

PALE_GREEN = (0.85, 1.0, 0.85)   # 確定時
WHITE      = (1.0,  1.0, 1.0)    # キャンセル時

def mark_order_confirmed(order_no: str, *, cancel: bool = False) -> bool:
    """
    確定 (=淡い緑)／キャンセル (=白) の 2 役をこなす。
      cancel=True で白へ塗り戻す
      戻り値 True: 成功 / False: order_no が見つからない
    """
    rgb = WHITE if cancel else PALE_GREEN               # ← ここだけ分岐

    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_KEY)
    ws = get_or_create_worksheet(sh, "WebOrderRequests")

    ORDER_NO_COL = WEB_ORDER_COLUMN_KEYS.index("orderNo") + 1
    col_vals = ws.col_values(ORDER_NO_COL)

    try:
        row_idx = col_vals.index(order_no) + 1          # 1-origin
    except ValueError:
        return False

    ws.format(f"A{row_idx}:DA{row_idx}", {              # A〜DA くらいまで
        "backgroundColor": { "red": rgb[0], "green": rgb[1], "blue": rgb[2] }
    })
    return True

# -----------------------
# 動作確認用
# -----------------------
@app.route("/", methods=["GET"])
def health_check():
    return "LINE Bot is running.", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

