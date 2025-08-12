import os
import json
import time
from datetime import datetime
import pytz
import unicodedata  # ← 正規化のために追加

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

# 正規化ユーティリティ（追加）
def normalize_text(text):
    """
    Unicode NFC 正規化（例：「ト」＋「゛」→「ド」）
    """
    return unicodedata.normalize("NFC", text)

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
        elif title == "Simple Estimate_1":
            ws.update('A1:M1', [[
                "日時", "見積番号", "ユーザーID", "属性",
                "使用日(割引区分)", "商品名", "パターン", "枚数",
                "プリント位置", "色数", "背ネーム",
                "合計金額", "単価"
            ]])
    return ws

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

# ユーザの見積フロー管理用（簡易的セッション）
user_estimate_sessions = {}  # { user_id: {"step": n, "answers": {...}, "is_single": bool} }


from PRICE_TABLE_2025 import PRICE_TABLE_GENERAL, PRICE_TABLE_STUDENT

def calculate_estimate(estimate_data):
    item_raw = estimate_data.get("item", "")
    item = normalize_text(item_raw)
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
                    "text": "　ご利用者の属性を選択してください。",
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
    return FlexSendMessage(alt_text="　属性を選択してください", contents=flex_body)


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
                    "text": "　ご使用日は、今日より? \n　(注文日より使用日が14日目以降なら早割)",
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
    return FlexSendMessage(alt_text="　使用日を選択してください", contents=flex_body)

from datetime import datetime

def versioned_image(url: str) -> str:
    version = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{url}?v={version}"

def flex_item_select():
    def create_category_bubble(title, items):
        return {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "lg",
                "contents": [
                    {"type": "text", "text": f"❸商品カテゴリー：{title}", "weight": "bold", "size": "md", "align": "center"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "spacing": "md",
                                "contents": [
                                    *[{
                                        "type": "image",
                                        "url": url,
                                        "size": "lg",
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
                                "spacing": "md",
                                "contents": [
                                    *[{
                                        "type": "image",
                                        "url": url,
                                        "size": "lg",
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
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    categories = [
        ("Tシャツ系", [
            ("ドライTシャツ", f"https://catalog-bot-zf1t.onrender.com/dry_tshirt.png?v={now}"),
            ("ハイクオリティーTシャツ", f"https://catalog-bot-zf1t.onrender.com/high_quality_tshirt.png?v={now}"),
            ("ドライロングTシャツ", f"https://catalog-bot-zf1t.onrender.com/dry_long_tshirt.png?v={now}"),
            ("ドライポロシャツ", f"https://catalog-bot-zf1t.onrender.com/dry_polo.png?v={now}")
        ]),
        ("スポーツ系", [
            ("ゲームシャツ", f"https://catalog-bot-zf1t.onrender.com/game_shirt.png?v={now}"),
            ("ベースボールシャツ", f"https://catalog-bot-zf1t.onrender.com/baseball_shirt.png?v={now}"),
            ("ストライプベースボールシャツ", f"https://catalog-bot-zf1t.onrender.com/stripe_baseball.png?v={now}"),
            ("ストライプユニフォーム", f"https://catalog-bot-zf1t.onrender.com/stripe_uniform.png?v={now}")
        ]),
        ("トレーナー系", [
            ("クールネックライトトレーナー", f"https://catalog-bot-zf1t.onrender.com/crew_trainer.png?v={now}"),
            ("ジップアップライトトレーナー", f"https://catalog-bot-zf1t.onrender.com/zip_trainer.png?v={now}"),
            ("フーディーライトトレーナー", f"https://catalog-bot-zf1t.onrender.com/hoodie_trainer.png?v={now}"),
            ("バスケシャツ", f"https://catalog-bot-zf1t.onrender.com/basketball_shirt.png?v={now}")
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


from datetime import datetime
from linebot.models import FlexSendMessage

def flex_pattern_select(product_name):
    patterns = ["A", "B", "C", "D", "E", "F"]
    bubbles = []

    version = datetime.now().strftime("%Y%m%d%H%M%S")

    for p in patterns:
        image_url = f"https://catalog-bot-zf1t.onrender.com/{product_name}_{p}.png?v={version}"
        bubbles.append({
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": image_url,
                "size": "full",
                "aspectMode": "cover",
                "aspectRatio": "1:1"
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
                            "label": f"パターン{p}で金額を確認",  # 表示用
                            "text": f"パターン{p}"              # 実際に送るメッセージ
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
                    "text": "　必要枚数を選択してください。",
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

from datetime import datetime
from linebot.models import FlexSendMessage

def flex_estimate_result_with_image(estimate_data, total_price, unit_price, quote_number):
    item_raw = estimate_data["item"]
    item = normalize_text(item_raw)
    pattern_raw = estimate_data.get("pattern", "")
    pattern = pattern_raw.replace("パターン", "").strip()

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    image_url = f"https://catalog-bot-zf1t.onrender.com/{item}_{pattern}.png?v={timestamp}"
    alt_text = f"{item}の見積結果"

    flex = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": "概算見積",
                    "weight": "bold",
                    "size": "xl",
                    "align": "center"
                },
                {
                    "type": "image",
                    "url": image_url,
                    "size": "full",
                    "aspectMode": "cover",
                    "aspectRatio": "1:1"
                },
                {
                    "type": "box",
                    "layout": "baseline",
                    "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": "見積番号: ", "flex": 0},
                        {"type": "text", "text": quote_number, "wrap": True, "color": "#0000FF"}
                    ]
                },
                {"type": "text", "text": f"属性: {estimate_data['user_type']}"},
                {"type": "text", "text": f"使用日: {estimate_data['usage_date']}（{estimate_data['discount_type']}）"},
                {"type": "text", "text": f"商品: {estimate_data['item']}"},
                {"type": "text", "text": f"パターン: {estimate_data['pattern']}"},
                {"type": "text", "text": f"枚数: {estimate_data['quantity']}"},
                {"type": "separator"},
                {"type": "text", "text": f"【合計金額】{total_price:,}", "weight": "bold"},
                {"type": "text", "text": f"【1枚あたり】{unit_price:,}"},
                {"type": "separator"},
                {
                    "type": "text",
                    "text": "※より正確な金額をご希望の方は、下記からデザイン相談へお進みください。",
                    "wrap": True,
                    "size": "sm"
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
# 0) ハンドラ側でキャッチして動的 URL を返す
# -----------------------
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data or ""

    # --- デザイン相談 or 個別相談 選択時の応答 ---------------
    if data == "CONSULT_DESIGN":
        # セッション初期化
        if event.source.user_id in user_estimate_sessions:
            del user_estimate_sessions[event.source.user_id]

        message = (
            "有人チャットに接続いたします。\n"
            "ご検討中のデザインがございましたら、画像やイラストなどの資料をお送りくださいませ。\n\n"
            "※当ショップの営業時間は【10:00～19:00】でございます。\n"
            "営業時間外にいただいたお問い合わせにつきましては、確認でき次第、順次ご対応させていただきます。\n"
            "何卒ご理解賜りますようお願い申し上げます。\n\n"
            "その他ご要望やご不明点がございましたら、お気軽にメッセージをお送りくださいませ。\n"
            "どうぞよろしくお願いいたします。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=message))
        return

    if data == "CONSULT_PERSONAL":
        # セッション初期化
        if event.source.user_id in user_estimate_sessions:
            del user_estimate_sessions[event.source.user_id]

        message = (
            "スタッフによるチャット対応を開始いたします。\n"
            "ご検討中の商品について、金額やデザインに関するご質問がございましたら、こちらからお気軽にご相談ください。\n\n"
            "※当ショップの営業時間は【10:00～19:00】です。\n"
            "営業時間外にいただいたお問い合わせにつきましては、確認でき次第、順次ご対応させていただきます。\n"
            "あらかじめご了承くださいませ。\n\n"
            "そのほか、ご要望やご不明点がございましたら、メッセージにてお知らせください。\n"
            "よろしくお願いいたします。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=message))
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
        # セッションを初期化しておく
        if user_id in user_estimate_sessions:
            del user_estimate_sessions[user_id]

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
        "📢 現在のキャンペーン情報\n"
        "現在、実施中のキャンペーンはございません🙇‍♀️\n"
        "今後、お得なキャンペーンやプレゼント企画などを予定しておりますので、"
        "ぜひLINEをお友だち登録したままお待ちいただけますと嬉しいです🎁✨\n"
        "新着情報は、LINEや各SNSで随時お知らせいたします！\n\n"
        "📸 Instagramはこちら\n"
        "商品紹介や制作事例、お客様の声などを日々アップしています！\n"
        "ぜひチェック＆フォローをよろしくお願いします👇\n"
        "👉 https://www.instagram.com/original_tshirt_3tlab/\n\n"
        "🎵 TikTokはこちら\n"
        "制作風景や裏側、スタッフの日常などを楽しくお届け中📹✨\n"
        "フォローして最新動画をお見逃しなく👇\n"
        "👉 https://www.tiktok.com/@3tlab_original_tshirt\n\n"
        "皆さまの応援が励みになります😊\n"
        "今後ともどうぞよろしくお願いいたします！"
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
            session_data["step"] = 6
            est_data = session_data["answers"]
            total_price, unit_price = calculate_estimate(est_data)

            # ▼ 見積番号とフォームURL生成
            quote_number = str(int(time.time()))
            form_url = f"https://bro-shop-test.onrender.com/quotation_form?quote_no={quote_number}"

            # ▼ 書き込み用form_dataに変換
            form_data = {
                "quote_no": quote_number,
                "user_id": user_id,
                "attribute": est_data["user_type"],
                "usage_date": f"{est_data['usage_date']}({est_data['discount_type']})",
                "product_category": est_data["item"],
                "pattern": est_data["pattern"],
                "quantity": est_data["quantity"],
                "total_price": total_price,   # ←文字列にせず数値で渡す
                "unit_price": unit_price,
                "print_position": "",  # オプション未使用
                "print_color": "",  # オプション未使用
                "print_size": "",  # オプション未使用
                "print_design": "",  # オプション未使用
                "form_url": form_url
            }

            # ▼ 統合スプレッドシート書き込み
            write_to_quotation_spreadsheet(form_data)

            # ▼ Flex メッセージ送信
            flex_msg = flex_estimate_result_with_image(est_data, total_price, unit_price, quote_number)
            line_bot_api.reply_message(event.reply_token, flex_msg)

            del user_estimate_sessions[user_id]
        else:
            del user_estimate_sessions[user_id]
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="入力内容に誤りがあります。もう一度「カンタン見積り」からやり直してください。")
            )

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

# -----------------------
# カンタン見積管理HTMLの処理
# -----------------------

@app.route("/quotation_form", methods=["GET"])
def show_quotation_form():
    token = str(uuid.uuid4())
    session['quotation_form_token'] = token

    quote_no = request.args.get("quote_no", "").strip()
    prefill_data = {}

    if quote_no:
        try:
            gc = get_gspread_client()
            sh = gc.open_by_key(SPREADSHEET_KEY)
            ws = sh.worksheet("Simple Estimate_1")
            all_rows = ws.get_all_records()
            for row in all_rows:
                if str(row.get("見積番号")) == quote_no:
                    # 日本語列名 → 英語キーの変換
                    prefill_data = {
                        "quote_no": row.get("見積番号", ""),
                        "user_id": row.get("ユーザーID", ""),
                        "attribute": row.get("属性", ""),
                        "usage_date": row.get("使用日(割引区分)", ""),
                        "product_category": row.get("商品カテゴリー", ""),
                        "pattern": row.get("パターン", ""),
                        "quantity": row.get("枚数", ""),
                        "total_price": row.get("合計金額", ""),
                        "unit_price": row.get("単価", ""),
                        "print_position": row.get("プリント位置", ""),
                        "print_color": row.get("プリントカラー", ""),
                        "print_size": row.get("プリントサイズ", ""),
                        "print_design": row.get("プリントデザイン", ""),
                        "form_url": row.get("見積番号管理WEBフォームURL", ""),

                        # ボディ情報
                        "body_code": row.get("ボディ品番", ""),
                        "body_name": row.get("ボディ商品名", ""),
                        "body_color_no": row.get("ボディカラーNo", ""),
                        "body_color": row.get("商品カラー", ""),
                        "size_count_SS": row.get("SS", ""),
                        "size_count_S": row.get("S", ""),
                        "size_count_M": row.get("M", ""),
                        "size_count_L": row.get("L", ""),
                        "size_count_XL": row.get("XL", ""),
                        "size_count_XXL": row.get("XXL", ""),
                        "size_count_XXXL": row.get("XXXL", ""),
                        "size_count_XXXXL": row.get("XXXXL", ""),

                        "order_count": row.get("注文数", ""),

                        # プリント箇所情報
                        "print_area_count": row.get("プリント箇所数", ""),
                        "print_position_1": row.get("プリント位置_1", ""),
                        "print_design_1": row.get("プリントデザイン_1", ""),
                        "print_color_count_1": row.get("プリントカラー数_1", ""),
                        "print_color_1": row.get("プリントカラー_1", ""),
                        "print_size_1": row.get("デザインサイズ_1", ""),

                        "print_position_2": row.get("プリント位置_2", ""),
                        "print_design_2": row.get("プリントデザイン_2", ""),
                        "print_color_count_2": row.get("プリントカラー数_2", ""),
                        "print_color_2": row.get("プリントカラー_2", ""),
                        "print_size_2": row.get("デザインサイズ_2", ""),

                        "print_position_3": row.get("プリント位置_3", ""),
                        "print_design_3": row.get("プリントデザイン_3", ""),
                        "print_color_count_3": row.get("プリントカラー数_3", ""),
                        "print_color_3": row.get("プリントカラー_3", ""),
                        "print_size_3": row.get("デザインサイズ_3", ""),

                        "print_position_4": row.get("プリント位置_4", ""),
                        "print_design_4": row.get("プリントデザイン_4", ""),
                        "print_color_count_4": row.get("プリントカラー数_4", ""),
                        "print_color_4": row.get("プリントカラー_4", ""),
                        "print_size_4": row.get("デザインサイズ_4", ""),
                        "jersey_number": row.get("背番号", ""),
                        "jersey_name": row.get("背ネーム", ""),
                        "jersey_number_color": row.get("背番号カラー", ""),
                        "jersey_name_color": row.get("背ネームカラー", ""),
                        "outline_enabled": row.get("フチ付き", ""),
                        "symbol": row.get("記号", ""),

                        # 加工・納期
                        "processing_method": row.get("加工方法", ""),
                        "delivery_date": row.get("納期", ""),
                        "payment_method": row.get("支払い方法", ""),

                        # 備考欄
                        "special_spec": row.get("特殊仕様", ""),
                        "requested_delivery": row.get("希望納期", ""),
                        "packaging": row.get("袋詰め有無", ""),
                        "other_notes": row.get("その他備考", "") or row.get("その他", ""),  # 旧名にも対応

                        # 確定後反映項目
                        "pattern_fee": row.get("パターン料金", ""),
                        "lot_size": row.get("枚数(ロット)", ""),
                        "shipping_fee": row.get("送料", ""),
                        "delivery_request_date": row.get("納期(希望日)", "")
                    }
                    break
        except Exception as e:
            print("読み取りエラー:", e)

    try:
        with open("select_options.json", encoding="utf-8") as f:
            options = json.load(f)
    except Exception as e:
        options = {}
        print("選択肢読み込みエラー:", e)

    return render_template("quotation_form.html", token=token, prefill=prefill_data, options=options)

@app.route("/submit_quotation", methods=["POST"])
def submit_quotation_form():
    form_token = request.form.get('form_token')
    if form_token != session.get('quotation_form_token'):
        return "二重送信、または不正なアクセスです。", 400

    session.pop('quotation_form_token', None)

    form_data = {
        "quote_no": request.form.get("quote_no", "").strip(),
        "user_id": request.form.get("user_id", "").strip(),
        "attribute": request.form.get("attribute", "").strip(),
        "usage_date": request.form.get("usage_date", "").strip(),
        "product_category": request.form.get("product_category", "").strip(),
        "pattern": request.form.get("pattern", "").strip(),
        "quantity": request.form.get("quantity", "").strip(),
        "total_price": request.form.get("total_price", "").strip(),
        "unit_price": request.form.get("unit_price", "").strip(),
        "print_position": request.form.get("print_position", "").strip(),
        "print_color": request.form.get("print_color", "").strip(),
        "print_size": request.form.get("print_size", "").strip(),
        "print_design": request.form.get("print_design", "").strip(),
        "form_url": request.form.get("form_url", "").strip(),

        # ボディ情報
        "body_code": request.form.get("body_code", "").strip(),
        "body_name": request.form.get("body_name", "").strip(),
        "body_color_no": request.form.get("body_color_no", "").strip(),
        "body_color": request.form.get("body_color", "").strip(),
        "size_count_SS": request.form.get("size_count_SS", "").strip(),
        "size_count_S": request.form.get("size_count_S", "").strip(),
        "size_count_M": request.form.get("size_count_M", "").strip(),
        "size_count_L": request.form.get("size_count_L", "").strip(),
        "size_count_XL": request.form.get("size_count_XL", "").strip(),
        "size_count_XXL": request.form.get("size_count_XXL", "").strip(),
        "size_count_XXXL": request.form.get("size_count_XXXL", "").strip(),
        "size_count_XXXXL": request.form.get("size_count_XXXXL", "").strip(),
        "order_count": request.form.get("order_count", "").strip(),

        # プリント箇所
        "print_area_count": request.form.get("print_area_count", "").strip(),
        "processing_method": request.form.get("processing_method", "").strip(),
        "delivery_date": request.form.get("delivery_date", "").strip(),
        "jersey_number": request.form.get("jersey_number", "").strip(),
        "jersey_name": request.form.get("jersey_name", "").strip(),
        "jersey_number_color": request.form.get("jersey_number_color", "").strip(),
        "jersey_name_color": request.form.get("jersey_name_color", "").strip(),
        "outline_enabled": request.form.get("outline_enabled", "").strip(),
        "symbol": request.form.get("symbol", "").strip(),

        # 備考欄
        "special_spec": request.form.get("special_spec", "").strip(),
        "requested_delivery": request.form.get("requested_delivery", "").strip(),
        "packaging": request.form.get("packaging", "").strip(),
        "other_notes": request.form.get("other_notes", "").strip(),

        # 確定後
        "pattern_fee": request.form.get("pattern_fee", "").strip(),
        "lot_size": request.form.get("lot_size", "").strip(),
        "shipping_fee": request.form.get("shipping_fee", "").strip(),
        "delivery_request_date": request.form.get("delivery_request_date", "").strip(),
        "payment_method": request.form.get("payment_method", "").strip(),
    }

    # 1～4 箇所分のプリント情報（ループで取得）
    for i in range(1, 5):
        form_data[f"print_position_{i}"] = request.form.get(f"print_position_{i}", "").strip()
        form_data[f"print_design_{i}"] = request.form.get(f"print_design_{i}", "").strip()
        form_data[f"print_color_count_{i}"] = request.form.get(f"print_color_count_{i}", "").strip()
        form_data[f"print_color_{i}"] = request.form.get(f"print_color_{i}", "").strip()
        form_data[f"print_size_{i}"] = request.form.get(f"print_size_{i}", "").strip()

    try:
        write_to_quotation_spreadsheet(form_data)
    except Exception as e:
        return f"エラーが発生しました: {e}", 500

    return "見積内容を保存しました。", 200


import gspread.utils  # 列文字変換のために追加

def write_to_quotation_spreadsheet(form_data: dict):
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_KEY)

    try:
        worksheet = sh.worksheet("Simple Estimate_1")

        # ★ ヘッダーが空のままになっている既存シートを救済
        if not any(worksheet.row_values(1)):
            worksheet.update('A1:BN1', [[
                "日時", "見積番号", "ユーザーID", "属性", "使用日(割引区分)",
                "商品カテゴリー", "パターン", "枚数", "合計金額", "単価",
                "プリント位置", "プリントカラー", "プリントサイズ", "プリントデザイン", "見積番号管理WEBフォームURL",
                "ボディ品番", "ボディ商品名", "ボディカラーNo", "商品カラー", "SS", "S", "M", "L", "XL", "XXL", "XXXL", "XXXXL", "注文数",
                "プリント箇所数",
                "プリント位置_1", "プリントデザイン_1", "プリントカラー数_1", "プリントカラー_1", "デザインサイズ_1",
                "プリント位置_2", "プリントデザイン_2", "プリントカラー数_2", "プリントカラー_2", "デザインサイズ_2",
                "プリント位置_3", "プリントデザイン_3", "プリントカラー数_3", "プリントカラー_3", "デザインサイズ_3",
                "プリント位置_4", "プリントデザイン_4", "プリントカラー数_4", "プリントカラー_4", "デザインサイズ_4",
                "背番号", "背ネーム", "背番号カラー", "背ネームカラー", "フチ付き", "記号",
                "加工方法", "納期","支払い方法",
                "特殊仕様", "希望納期", "袋詰め有無", "その他備考",
                "パターン料金", "枚数(ロット)", "送料", "納期(希望日)"
            ]])

    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title="Simple Estimate_1", rows=2000, cols=100)
        worksheet.update('A1:BN1', [[
            "日時", "見積番号", "ユーザーID", "属性", "使用日(割引区分)",
            "商品カテゴリー", "パターン", "枚数", "合計金額", "単価",
            "プリント位置", "プリントカラー", "プリントサイズ", "プリントデザイン", "見積番号管理WEBフォームURL",

            "ボディ品番", "ボディ商品名", "ボディカラーNo", "商品カラー", "SS", "S", "M", "L", "XL", "XXL", "XXXL", "XXXXL", "注文数",
            "プリント箇所数",
            "プリント位置_1", "プリントデザイン_1", "プリントカラー数_1", "プリントカラー_1", "デザインサイズ_1",
            "プリント位置_2", "プリントデザイン_2", "プリントカラー数_2", "プリントカラー_2", "デザインサイズ_2",
            "プリント位置_3", "プリントデザイン_3", "プリントカラー数_3", "プリントカラー_3", "デザインサイズ_3",
            "プリント位置_4", "プリントデザイン_4", "プリントカラー数_4", "プリントカラー_4", "デザインサイズ_4",
            "背番号", "背ネーム", "背番号カラー", "背ネームカラー", "フチ付き", "記号",
            "加工方法", "納期","支払い方法",
            "特殊仕様", "希望納期", "袋詰め有無", "その他備考",
            "パターン料金", "枚数(ロット)", "送料", "納期(希望日)"
        ]])

    jst = pytz.timezone('Asia/Tokyo')
    now_str = datetime.now(jst).strftime("%Y/%m/%d %H:%M:%S")

    new_row = [
        now_str,
        form_data.get("quote_no", ""),
        form_data.get("user_id", ""),
        form_data.get("attribute", ""),
        form_data.get("usage_date", ""),
        form_data.get("product_category", ""),
        form_data.get("pattern", ""),
        form_data.get("quantity", ""),
        form_data.get("total_price", ""),
        form_data.get("unit_price", ""),
        form_data.get("print_position", ""),
        form_data.get("print_color", ""),
        form_data.get("print_size", ""),
        form_data.get("print_design", ""),
        form_data.get("form_url", ""),

        form_data.get("body_code", ""),
        form_data.get("body_name", ""),
        form_data.get("body_color_no", ""),
        form_data.get("body_color", ""),
        form_data.get("size_count_SS", ""),
        form_data.get("size_count_S", ""),
        form_data.get("size_count_M", ""),
        form_data.get("size_count_L", ""),
        form_data.get("size_count_XL", ""),
        form_data.get("size_count_XXL", ""),
        form_data.get("size_count_XXXL", ""),
        form_data.get("size_count_XXXXL", ""),

        form_data.get("order_count", ""),
        form_data.get("print_area_count", ""),

        form_data.get("print_position_1", ""),
        form_data.get("print_design_1", ""),
        form_data.get("print_color_count_1", ""),
        form_data.get("print_color_1", ""),
        form_data.get("print_size_1", ""),

        form_data.get("print_position_2", ""),
        form_data.get("print_design_2", ""),
        form_data.get("print_color_count_2", ""),
        form_data.get("print_color_2", ""),
        form_data.get("print_size_2", ""),

        form_data.get("print_position_3", ""),
        form_data.get("print_design_3", ""),
        form_data.get("print_color_count_3", ""),
        form_data.get("print_color_3", ""),
        form_data.get("print_size_3", ""),

        form_data.get("print_position_4", ""),
        form_data.get("print_design_4", ""),
        form_data.get("print_color_count_4", ""),
        form_data.get("print_color_4", ""),
        form_data.get("print_size_4", ""),

        form_data.get("jersey_number", ""),
        form_data.get("jersey_name", ""),
        form_data.get("jersey_number_color", ""),
        form_data.get("jersey_name_color", ""),
        form_data.get("outline_enabled", ""),
        form_data.get("symbol", ""),

        form_data.get("processing_method", ""),
        form_data.get("delivery_date", ""),
        form_data.get("payment_method", ""),


        form_data.get("special_spec", ""),
        form_data.get("requested_delivery", ""),
        form_data.get("packaging", ""),
        form_data.get("other_notes", ""),

        form_data.get("pattern_fee", ""),
        form_data.get("lot_size", ""),
        form_data.get("shipping_fee", ""),
        form_data.get("delivery_request_date", "")
    ]

    records = worksheet.get_all_values()
    quote_no = form_data.get("quote_no", "")

    for idx, row in enumerate(records[1:], start=2):  # Skip header
        if row[1] == quote_no:
            end_col_letter = gspread.utils.rowcol_to_a1(1, len(new_row)).split("1")[0]
            worksheet.update(f"A{idx}:{end_col_letter}{idx}", [new_row])
            return

    worksheet.append_row(new_row, value_input_option="USER_ENTERED")


# -----------------------
# 動作確認用
# -----------------------
@app.route("/", methods=["GET"])
def health_check():
    return "LINE Bot is running.", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

