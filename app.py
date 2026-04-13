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

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# 最新のAIモデルを指定
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

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="画像をAIで解析中...🤖🔍\n10秒ほどお待ちください！"))

    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b""
        for chunk in message_content.iter_content():
            image_data += chunk
            
        # 【プロの書き方】with構文で画像を開き、処理が終わったら自動でメモリから完全に消去する
        with Image.open(io.BytesIO(image_data)) as img:
            prompt = "この画像に写っている植生を解析してください。竹(bamboo)、樹木(tree)、雑草(weed)の割合を合計100になるように推論してください。回答は必ずカンマ区切りの数字3つのみ（例：40,45,15）としてください。"
            response = model.generate_content([prompt, img])
            ai_result = response.text.strip()
        
        # ※ここに来た時点で、画像データは安全にシュレッダーにかけられています！
        print(f"【AIの生返答】: {ai_result}")
        
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

        line_bot_api.push_message(
            user_id, 
            TextSendMessage(text=f"✨解析が完了しました！✨\n🎋 竹・笹: 約{bamboo_pct}%\n🌳 樹木: 約{tree_pct}%\n🌿 雑草: 約{weed_pct}%\n\n次に、対象の「面積（㎡）」を数字だけで送信してください！\n（例：150）")
        )

    except Exception as e:
        print(f"【エラー発生】: {e}")
        line_bot_api.push_message(user_id, TextSendMessage(text="申し訳ありません、画像の解析に失敗しました。別の写真でお試しください🙇‍♂️"))

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if user_id in user_states:
        try:
            area_sqm = int(text)
            state = user_states[user_id]
            bamboo_pct = state['bamboo']
            tree_pct = state['tree']
            weed_pct = state['weed']
            
            cost = (area_sqm * (bamboo_pct/100) * 2500) + (area_sqm * (tree_pct/100) * 1000) + (area_sqm * (weed_pct/100) * 500)
            final_cost = int(cost)

            reply_text = (f"面積（{area_sqm}㎡）から算出した概算費用は...\n\n👉 【 {final_cost:,} 円 】 です！\n\n※AIでの分析のため、実際の料金とは異なります。\n※正確な金額は現地調査にて確定いたします。\n※後日こちらのLINEへ担当者から連絡が来ます。")
            
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            del user_states[user_id]

        except ValueError:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="面積は「150」のように半角数字のみで入力してください🙇‍♂️"))
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="AI見積もりを行うには、まず対象となるお庭や竹林の「写真」を送信してください📸"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
