import os
import io
import re
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import google.generativeai as genai
from PIL import Image

app = Flask(__name__)

@app.route("/")
def keep_alive():
    return "OK"

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

model = genai.GenerativeModel('gemini-2.5-flash')

user_states = {}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ▼ 1. 画像が送られてきた時の処理
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="画像をAIで解析中...🤖🔍\n10秒ほどお待ちください！"))

    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b""
        for chunk in message_content.iter_content():
            image_data += chunk
            
        with Image.open(io.BytesIO(image_data)) as img:
            prompt = "この画像に写っている植生を解析してください。竹(bamboo)、樹木(tree)、雑草(weed)の割合を合計100になるように推論してください。回答は必ずカンマ区切りの数字3つのみ（例：40,45,15）としてください。"
            response = model.generate_content([prompt, img])
            ai_result = response.text.strip()
        
        print(f"【画像解析の生返答】: {ai_result}")
        numbers = re.findall(r'\d+', ai_result)
        
        if len(numbers) >= 3:
            bamboo_pct, tree_pct, weed_pct = map(int, numbers[:3])
        else:
            raise ValueError(f"AIが数値を正しく返しませんでした。取得データ: {ai_result}")

        user_states[user_id] = {
            'bamboo': bamboo_pct,
            'tree': tree_pct,
            'weed': weed_pct
        }

        # 【変更】面積だけでなく、伐採の希望範囲も聞くようにメッセージを変更
        reply_msg = (f"✨解析が完了しました！✨\n"
                     f"🎋 竹・笹: 約{bamboo_pct}%\n🌳 樹木: 約{tree_pct}%\n🌿 雑草: 約{weed_pct}%\n\n"
                     f"次に、対象の「面積（㎡）」と「伐採したい範囲・種類」をメッセージで教えてください！\n\n"
                     f"（例：「150平米、竹だけ切って」「50㎡、全部お願いします」など）")
        
        line_bot_api.push_message(user_id, TextSendMessage(text=reply_msg))

    except Exception as e:
        print(f"【画像エラー発生】: {e}")
        line_bot_api.push_message(user_id, TextSendMessage(text="申し訳ありません、画像の解析に失敗しました。別の写真でお試しください🙇‍♂️"))


# ▼ 2. メッセージ（面積や条件）が送られてきた時の処理
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if user_id in user_states:
        # お客様を待たせないよう、先に「計算中」と送る
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ご要望を読み取って計算中です...💻✨\n少々お待ちください！"))
        
        try:
            # 【新規】AIにお客様のメッセージを解読させる
            prompt = f"""
            あなたは伐採費用の見積もりAIです。
            ユーザーからのメッセージ: 「{text}」
            
            このメッセージから「面積(㎡)」と「伐採したい対象」を読み取ってください。
            以下のカンマ区切りのフォーマットでだけ返答してください。余計な文字は一切不要です。
            
            フォーマット: [面積の数字],[竹が対象か(1or0)],[木が対象か(1or0)],[雑草が対象か(1or0)]
            
            ルール:
            - 面積が書かれていない場合は 0 としてください。
            - 対象の指定がない（「150平米」だけ等）場合は、全て対象として 1,1,1 にしてください。
            - 「竹だけ」なら 1,0,0 にしてください。
            - 「雑草と木」なら 0,1,1 にしてください。
            """
            
            response = model.generate_content(prompt)
            ai_result = response.text.strip()
            print(f"【テキスト解読結果】: {ai_result}")
            
            # AIが出した答えから、面積と対象フラグを取り出す
            numbers = re.findall(r'\d+', ai_result)
            if len(numbers) >= 4:
                area_sqm = int(numbers[0])
                calc_bamboo = int(numbers[1])
                calc_tree = int(numbers[2])
                calc_weed = int(numbers[3])
            else:
                raise ValueError("解読失敗")

            # もし面積が読み取れなかったら、聞き返す（メモリは消さない）
            if area_sqm == 0:
                line_bot_api.push_message(user_id, TextSendMessage(text="面積が読み取れませんでした。「150平米」のように広さの数字を教えていただけますか？🙇‍♂️"))
                return

            # 保存しておいた画像解析結果を呼び出す
            state = user_states[user_id]
            bamboo_pct = state['bamboo']
            tree_pct = state['tree']
            weed_pct = state['weed']
            
            # お客様の指定に合わせて計算する
            cost = 0
            target_names = []
            
            if calc_bamboo == 1:
                cost += (area_sqm * (bamboo_pct/100) * 4000)
                target_names.append("🎋 竹・笹")
            if calc_tree == 1:
                cost += (area_sqm * (tree_pct/100) * 3000)
                target_names.append("🌳 樹木")
            if calc_weed == 1:
                cost += (area_sqm * (weed_pct/100) * 500)
                target_names.append("🌿 雑草")

            final_cost = int(cost)
            target_str = "、".join(target_names) if target_names else "指定なし"

            # 最終結果の送信
            reply_text = (f"ご要望に合わせて計算しました！\n\n"
                          f"📐 面積: {area_sqm}㎡\n"
                          f"🎯 対象: {target_str}\n"
                          f"👉 概算費用: 【 {final_cost:,} 円 】 です！\n\n"
                          f"※資源化による処分費カットを適用済みの価格です。\n"
                          f"※正確な金額は現地調査にて確定いたします。")
            
            line_bot_api.push_message(user_id, TextSendMessage(text=reply_text))
            
            # 計算が終わったのでメモリをリセット
            del user_states[user_id]

        except Exception as e:
            print(f"【テキスト解読エラー】: {e}")
            line_bot_api.push_message(user_id, TextSendMessage(text="申し訳ありません、メッセージの解読に失敗しました。「150平米、竹だけ」のように分かりやすく入力していただけますか？🙇‍♂️"))
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="AI見積もりを行うには、まず対象となるお庭や竹林の「写真」を送信してください📸"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
