import os
import io
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, ImageMessage, TextSendMessage
import google.generativeai as genai
from PIL import Image

app = Flask(__name__)

# 3つの鍵
line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

model = genai.GenerativeModel('gemini-1.5-flash')

# 【追加】ユーザーの状態を一時保存する「メモリ」
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

# ▼ ユーザーが「画像」を送ってきた時の処理
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="画像をAIで解析中...🤖🔍\n10秒ほどお待ちください！"))

    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_data = b""
        for chunk in message_content.iter_content():
            image_data += chunk
        img = Image.open(io.BytesIO(image_data))

        prompt = "この画像に写っている植生を解析してください。竹(bamboo)、樹木(tree)、雑草(weed)の割合を合計100になるように推論し、カンマ区切りの数字のみ（例：40,45,15）で返してください。"
        
        response = model.generate_content([prompt, img])
        ai_result = response.text.strip()
        
        bamboo_pct, tree_pct, weed_pct = map(int, ai_result.split(','))
        
        # 【追加】解析結果をそのユーザーのIDに紐づけて保存する
        user_states[user_id] = {
            'bamboo': bamboo_pct,
            'tree': tree_pct,
            'weed': weed_pct
        }

        # 解析完了と、面積の入力を促すメッセージを送信
        line_bot_api.push_message(
            user_id, 
            TextSendMessage(text=f"✨解析が完了しました！✨\n🎋 竹・笹: 約{bamboo_pct}%\n🌳 樹木: 約{tree_pct}%\n🌿 雑草: 約{weed_pct}%\n\n次に、対象の「面積（㎡）」を数字だけで送信してください！\n（例：150）")
        )

    except Exception as e:
        print(f"Error: {e}")
        line_bot_api.push_message(user_id, TextSendMessage(text="申し訳ありません、画像の解析に失敗しました。別の写真でお試しください🙇‍♂️"))

# ▼ ユーザーが「文字（面積）」を送ってきた時の処理
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    # もしユーザーが画像をすでに送っていて、メモリに記録があるなら
    if user_id in user_states:
        try:
            # 入力された文字を数字（面積）に変換
            area_sqm = int(text)
            
            # 保存しておいたAIの解析結果を呼び出す
            state = user_states[user_id]
            bamboo_pct = state['bamboo']
            tree_pct = state['tree']
            weed_pct = state['weed']
            
            # 金額の計算ロジック
            cost = (area_sqm * (bamboo_pct/100) * 4000) + (area_sqm * (tree_pct/100) * 3000) + (area_sqm * (weed_pct/100) * 500)
            final_cost = int(cost)

            reply_text = (f"面積（{area_sqm}㎡）から算出した概算費用は...\n\n👉 【 {final_cost:,} 円 】 です！\n\n※資源化による処分費カットを適用済みの価格です。\n※正確な金額は現地調査にて確定いたします。")
            
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            
            # 見積もり完了後、次の計算のためにメモリをリセット
            del user_states[user_id]

        except ValueError:
            # 数字以外（「150平米です」など）が送られてきた場合のエラー回避
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="面積は「150」のように半角数字のみで入力してください🙇‍♂️"))
    
    # 画像を送らずにいきなり文字を送ってきた場合
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="AI見積もりを行うには、まず対象となるお庭や竹林の「写真」を送信してください📸"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
