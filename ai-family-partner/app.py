import os
import sys
import numpy as np
import soundfile as sf
import torch
import gradio as gr

# --- 1. モデルの初期化 ---
device = "cuda:0" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
dtype = torch.float16 if device == "cuda:0" else torch.float32

print(f"Loading OmniVoice on {device}...")
from omnivoice import OmniVoice, VoiceClonePrompt
model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=device, dtype=dtype)

# FlashInfer 高速化（利用可能時）
try:
    from omnivoice.models.omnivoice_flashinfer import apply_flashinfer
    apply_flashinfer(model, enable_cuda_graph=True)
    print("FlashInfer enabled.")
except Exception:
    pass

# --- 2. OpenAI / Whisper のセットアップ ---
api_key = os.getenv("OPENAI_API_KEY")
use_openai = bool(api_key)

if use_openai:
    import openai
    client = openai.OpenAI(api_key=api_key)
else:
    import whisper
    local_whisper = whisper.load_model("base")

# プロンプト定義
PROMPTS = {
    "シニア向け（昔話・傾聴）": """
あなたは一人暮らしのお年寄りの話し相手をする、優しく親しみやすい家族（お孫さんや親しい親族）です。
1. 温かい相づち（「うんうん」「そうなんだぁ」）を必ず入れる。
2. 返答は2〜3文程度で簡潔にし、昭和の暮らしや昔の思い出を引き出す質問を1つ返す。
3. 和やかな笑いを入れる箇所は [laughter] と記述する。
4. 平易で聞き取りやすい日本語を使う。
""",
    "子ども向け（知育・おしゃべり）": """
あなたは小さな子どもの話し相手をする、優しく大好きな家族（お父さん・お母さん）です。
1. 子どもの言葉を「すごいね！」「面白いね！」とまず全力で肯定する。
2. 難しい言葉は使わず、動物や食べ物に例えて1〜2文でやさしく説明する。
3. 最後に「〇〇はどう思う？」と質問を返す。
4. 楽しそうに笑う場面には [laughter] を入れる。
"""
}

PROMPT_FILE = "active_voice.pt"
active_prompt = None
if os.path.exists(PROMPT_FILE):
    try:
        active_prompt = VoiceClonePrompt.load(PROMPT_FILE)
    except Exception:
        pass

# --- 3. 処理ロジック ---
def register_voice(audio_path):
    global active_prompt
    if not audio_path:
        return "音声ファイルがありません。"
    try:
        active_prompt = model.create_voice_clone_prompt(ref_audio=audio_path)
        active_prompt.save(PROMPT_FILE)
        return "✅ 声のクローン登録が完了しました！"
    except Exception as e:
        return f"登録エラー: {e}"

def chat_pipeline(audio_path, mode, history):
    if not audio_path:
        return None, history, "声が聞き取れませんでした。"

    # 文字起こし
    if use_openai:
        with open(audio_path, "rb") as f:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=f, language="ja")
        user_text = transcript.text.strip()
    else:
        res = local_whisper.transcribe(audio_path, language="ja")
        user_text = res["text"].strip()

    if not user_text:
        return None, history, "声が聞き取れませんでした。"

    # ChatGPT応答生成
    history.append({"role": "user", "content": user_text})
    
    if use_openai:
        messages = [{"role": "system", "content": PROMPTS[mode]}]
        for h in history[:-1]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_text})

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7
        )
        bot_text = completion.choices[0].message.content
    else:
        bot_text = "うんうん、よく聞こえたよ！[laughter] もっと色々なお話を聞かせてね！"

    history.append({"role": "assistant", "content": bot_text})

    # OmniVoice 音声合成
    # 子どもの場合は通常速度(1.0)、シニア向けは少しゆっくり(0.9)
    speed_val = 0.9 if "シニア" in mode else 1.0

    if active_prompt is not None:
        audio_out = model.generate(text=bot_text, voice_clone_prompt=active_prompt, num_step=16, speed=speed_val)
    else:
        # デフォルト声（穏やかな声質）
        audio_out = model.generate(text=bot_text, instruct="female, young adult, moderate pitch", num_step=16, speed=speed_val)

    # 保存（24kHz）
    out_wav = "response.wav"
    wav_data = (audio_out[0] * 32767).clip(-32768, 32767).astype(np.int16)
    sf.write(out_wav, wav_data, 24000)

    return out_wav, history, f"あなた: {user_text}\nAI: {bot_text}"

# --- 4. UI画面 ---
with gr.Blocks(title="AIファミリーパートナー") as demo:
    gr.Markdown("## 🌸 AIファミリーパートナー（ChatGPT × OmniVoice）")
    
    with gr.Tab("おしゃべり"):
        mode_select = gr.Radio(
            choices=["シニア向け（昔話・傾聴）", "子ども向け（知育・おしゃべり）"],
            value="シニア向け（昔話・傾聴）",
            label="対話モード選択"
        )
        chatbot = gr.Chatbot(type="messages", label="対話履歴")
        with gr.Row():
            mic_in = gr.Audio(sources=["microphone"], type="filepath", label="話しかける（マイク）")
            spk_out = gr.Audio(type="filepath", autoplay=True, label="お返事音声")
        status = gr.Textbox(label="会話ログ", interactive=False)

        mic_in.stop_recording(
            fn=chat_pipeline,
            inputs=[mic_in, mode_select, chatbot],
            outputs=[spk_out, chatbot, status]
        )

    with gr.Tab("声を登録（家族・自分）"):
        gr.Markdown("家族（親・孫など）の声を3〜5秒吹き込むと、その声で喋るようになります。")
        ref_in = gr.Audio(sources=["microphone", "upload"], type="filepath", label="サンプル音声")
        reg_btn = gr.Button("この声を登録する", variant="primary")
        reg_stat = gr.Textbox(label="登録状態")
        reg_btn.click(fn=register_voice, inputs=[ref_in], outputs=[reg_stat])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=True)
