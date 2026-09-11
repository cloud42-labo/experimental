import os
import sys
import tempfile
import uuid
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

# --- セッション分離のための一時ファイル管理 ---
# 声クローンプロンプト・応答音声のいずれも、プロセス／モジュールグローバルや
# リポジトリ内の固定パスには一切保存しない（AFP-01-T01）。
#   - 声クローンプロンプト: 登録のたびにシステム一時ディレクトリへ一意なファイル名で
#     書き出し、そのファイルパスだけを gr.State（＝ブラウザセッションごとに独立）に
#     保持する。ディスク上に「次回起動時の初期値」となるような永続ファイルは作らない
#     （起動時に過去の声を自動ロードしない）。
#   - 応答音声（response.wav相当）: 生成のたびに一意な一時ファイル名で書き出す。
#     同一セッション内の連続会話であっても前回のファイルを上書きしない。
#
# 新規DB・新規サービスは作らず、Python標準の tempfile のみで完結させる
# （Approach Decision通り）。
SESSION_TMP_DIR = os.path.join(tempfile.gettempdir(), "ai-family-partner-sessions")
os.makedirs(SESSION_TMP_DIR, exist_ok=True)

AI_DISCLOSURE_TEXT = (
    "🤖 **これはAIによる合成音声です。** ここで話しているのは本物のご家族本人ではなく、"
    "登録された声の特徴をもとにAIが生成した音声（ボイスクローン）です。"
)


def _new_temp_path(suffix):
    """SESSION_TMP_DIR配下に一意なファイルパスを発行する（作成はしない）。"""
    return os.path.join(SESSION_TMP_DIR, f"{uuid.uuid4().hex}{suffix}")


def _safe_remove(path):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


# --- 3. 処理ロジック ---
def register_voice(audio_path, consent, prev_voice_path):
    if not consent:
        return "⚠️ 本人（声の権利者）の同意確認にチェックが必要です。", prev_voice_path
    if not audio_path:
        return "音声ファイルがありません。", prev_voice_path
    try:
        prompt = model.create_voice_clone_prompt(ref_audio=audio_path)

        # このセッション専用の一意なパスへ保存する。プロセスグローバルな固定パス
        # （旧 active_voice.pt）は使わないため、他セッションや次回起動には一切影響しない。
        new_path = _new_temp_path(".pt")
        prompt.save(new_path)

        # 同じセッションで声を登録し直した場合、直前の一時ファイルは残さず片付ける。
        if prev_voice_path and prev_voice_path != new_path:
            _safe_remove(prev_voice_path)

        return "✅ 声のクローン登録が完了しました！（このセッションのみで利用されます）", new_path
    except Exception as e:
        return f"登録エラー: {e}", prev_voice_path


def chat_pipeline(audio_path, mode, history, session_voice_path):
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

    session_prompt = None
    if session_voice_path and os.path.exists(session_voice_path):
        try:
            session_prompt = VoiceClonePrompt.load(session_voice_path)
        except Exception:
            session_prompt = None

    if session_prompt is not None:
        audio_out = model.generate(text=bot_text, voice_clone_prompt=session_prompt, num_step=16, speed=speed_val)
    else:
        # デフォルト声（穏やかな声質）
        audio_out = model.generate(text=bot_text, instruct="female, young adult, moderate pitch", num_step=16, speed=speed_val)

    # 保存（24kHz）。呼び出しのたびに一意なファイル名で書き出すため、同時に使っている
    # 他セッションや、同じセッションの過去の応答と衝突・上書きしない。
    wav_data = (audio_out[0] * 32767).clip(-32768, 32767).astype(np.int16)
    response_path = _new_temp_path(".wav")
    sf.write(response_path, wav_data, 24000)

    return response_path, history, f"あなた: {user_text}\nAI: {bot_text}"


def reset_history_on_mode_change():
    # モードを切り替えたら会話履歴を必ずリセットする。シニア向け／子ども向けの
    # 会話が同じ履歴に混在してChatGPTへ渡ると、応答のトーンや文脈が意図せず
    # 混ざるため（AFP-01-T01 Acceptance Criteria）。
    return [], ""


# --- 4. UI画面 ---
with gr.Blocks(title="AIファミリーパートナー") as demo:
    gr.Markdown("## 🌸 AIファミリーパートナー（ChatGPT × OmniVoice）")
    gr.Markdown(AI_DISCLOSURE_TEXT)

    # ブラウザセッションごとに独立した状態。プロセス／モジュールグローバルではなく
    # gr.State に持たせることで、ある利用者の声クローン・会話履歴・生成音声が、
    # 同時に使っている別の利用者へ漏れないようにする。voice_state は
    # VoiceClonePrompt オブジェクトそのものではなく、一時ファイルのパス文字列のみを
    # 保持する（Approach Decision通り）。
    voice_state = gr.State(value=None)

    with gr.Tab("おしゃべり"):
        gr.Markdown(AI_DISCLOSURE_TEXT)
        mode_select = gr.Radio(
            choices=["シニア向け（昔話・傾聴）", "子ども向け（知育・おしゃべり）"],
            value="シニア向け（昔話・傾聴）",
            label="対話モード選択"
        )
        chatbot = gr.Chatbot(type="messages", label="対話履歴")
        with gr.Row():
            mic_in = gr.Audio(sources=["microphone"], type="filepath", label="話しかける（マイク）")
            spk_out = gr.Audio(type="filepath", autoplay=True, label="お返事音声（AI合成音声）")
        status = gr.Textbox(label="会話ログ", interactive=False)

        mic_in.stop_recording(
            fn=chat_pipeline,
            inputs=[mic_in, mode_select, chatbot, voice_state],
            outputs=[spk_out, chatbot, status]
        )

        # モード変更時は会話履歴を必ずリセットする（履歴の混在防止）。
        mode_select.change(
            fn=reset_history_on_mode_change,
            inputs=None,
            outputs=[chatbot, status]
        )

    with gr.Tab("声を登録（家族・自分）"):
        gr.Markdown("家族（親・孫など）の声を3〜5秒吹き込むと、その声で喋るようになります。")
        gr.Markdown(AI_DISCLOSURE_TEXT)
        gr.Markdown(
            "登録した声は、以降このAIが**合成音声として**発話するために使われます。"
            "本人（声の権利者）以外の声を、本人の同意なく登録しないでください。"
        )
        consent_check = gr.Checkbox(
            label="声の権利者本人の同意を得ています（本人以外の声を無断で登録しません）",
            value=False,
        )
        ref_in = gr.Audio(sources=["microphone", "upload"], type="filepath", label="サンプル音声")
        reg_btn = gr.Button("この声を登録する", variant="primary")
        reg_stat = gr.Textbox(label="登録状態")
        reg_btn.click(
            fn=register_voice,
            inputs=[ref_in, consent_check, voice_state],
            outputs=[reg_stat, voice_state]
        )

if __name__ == "__main__":
    # PoC期間中は公開共有リンクを作らない（README「安全設計の前提」の通り）。
    # 本人同意UI・セッション分離・AI明示等（Notion AFP-01-T01）が完了した後も、
    # 外部到達可能なGradio share linkは意図的に作らない。
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
