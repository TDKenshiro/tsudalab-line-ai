import os
import io
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import google.generativeai as genai
from PIL import Image

app = Flask(__name__)

# 3つの鍵を環境変数から読み込む
line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# 無料で高速なGeminiモデルを指定
model = genai.GenerativeModel('gemini-1.5-flash')

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
    # LINEで「処理中...」と表示させる（UX向上）
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="AIが画像を解析中...🤖🔍\n10秒ほどお待ちください！"))

    try:
        # 画像を取得してGeminiに渡す準備
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b""
        for chunk in message_content.iter_content():
            image_data += chunk
        img = Image.open(io.BytesIO(image_data))

        area_sqm = 150 # ※今回は固定値150平米で計算

        # AIへの指示（プロンプト）
        prompt = "この画像に写っている植生を解析してください。竹(bamboo)、樹木(tree)、雑草(weed)の割合を合計100になるように推論し、カンマ区切りの数字のみ（例：40,45,15）で返してください。"
        
        response = model.generate_content([prompt, img])
        ai_result = response.text.strip()
        
        # 数値を抽出して計算
        bamboo_pct, tree_pct, weed_pct = map(int, ai_result.split(','))
        cost = (area_sqm * (bamboo_pct/100) * 4000) + (area_sqm * (tree_pct/100) * 3000) + (area_sqm * (weed_pct/100) * 500)
        final_cost = int(cost)

        # 結果を送信
        reply_text = (f"✨【AI 画像解析結果】✨\n🎋 竹林・笹類: 約{bamboo_pct}%\n🌳 樹木・雑木: 約{tree_pct}%\n🌿 雑草・その他: 約{weed_pct}%\n\n面積（{area_sqm}㎡）から算出した概算費用は\n👉 {final_cost:,} 円 です！\n\n※正確な金額は現地調査にて確定します。")
        
        # 処理が完了したらプッシュメッセージで結果を送る
        line_bot_api.push_message(event.source.user_id, TextSendMessage(text=reply_text))

    except Exception as e:
        line_bot_api.push_message(event.source.user_id, TextSendMessage(text="申し訳ありません、画像の解析に失敗しました。別の写真でお試しください🙇‍♂️"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
