# AI Family Partner

ChatGPT × Whisper × OmniVoice を組み合わせ、家族の声で自然に対話できる音声対話パートナーを検証するプロダクト。

## 対象ユーザー

- 一人暮らしのシニア
- 3〜7歳程度の子ども
- 離れて暮らす家族

## コア体験

1. 利用者がマイクで話す
2. Whisper で文字起こしする
3. ChatGPT が利用者に合わせて短く応答する
4. OmniVoice が登録済みの家族の声で読み上げる
5. 利用者は画面操作をほぼせず会話を続けられる

## 初期ユースケース

### シニア向け
- 温かい相づちを入れる
- 返答は2〜3文程度
- 昔の暮らし・料理・歌・街並みなどの思い出を引き出す
- 平易で聞き取りやすい日本語を使う

### 子ども向け
- 「なんで？」「どうして？」を肯定する
- 身近な動物・食べ物・乗り物に例えて説明する
- 返答は1〜2文程度
- 最後に子どもが声を出したくなる質問を返す

## 技術構成

- 入力: Gradio / microphone
- STT: OpenAI Whisper または local Whisper
- 対話: OpenAI ChatGPT
- 音声出力: OmniVoice voice clone
- UI: Gradio

## PoCで検証する仮説

1. 家族の声は通常のAI音声より会話継続意欲を高めるか
2. シニアが画面操作なしで継続利用できるか
3. 子どもが自然に話しかけ続けるか
4. 応答待ち時間が会話体験を壊さないか
5. 家族の声を使うことによる安心感と誤認リスクを両立できるか

## 安全設計の前提

- 声の登録には本人の明示的な同意を必要とする
- 家族本人ではなく「家族の声で話すAI」であることを明示する
- 子ども利用は保護者管理を前提とする
- 声データと会話履歴を利用者ごとに分離する
- 外部公開用の `share=True` はPoC段階では使わない

## セットアップ・起動手順

```bash
cd experimental/ai-family-partner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# ChatGPT/Whisper-1 API を使う場合（推奨・応答品質が高い）
export OPENAI_API_KEY=sk-...

# OPENAI_API_KEY を設定しない場合はローカル Whisper (base) にフォールバックする。
# この場合 ChatGPT応答は固定文になる（app.py のフォールバック分岐を参照）。

python3 app.py
# => http://0.0.0.0:7860 で起動（share=Falseのため外部共有リンクは作られない）
```

### 依存関係の検証状況（2026-09-13 JST, AFP-01-T02-A）

`requirements.txt` に記載の全パッケージをクリーンなvenv（Python 3.11, CPU環境）へ
`pip install -r requirements.txt` でインストールし、`torch` / `gradio` / `numpy` /
`soundfile` / `openai` / `whisper` / `omnivoice` の import と `OmniVoice.from_pretrained`
呼び出し直前までの初期化コードパスを確認した。

- **CPU/MPS/CUDA判定**：この検証環境はCUDA/MPSともに利用不可のためCPU (`torch.float32`) を選択する分岐に入ることを確認した。
- **モデル重みのダウンロード**：`OmniVoice.from_pretrained("k2-fsa/OmniVoice", ...)` はHugging Face Hubへの到達が必要だが、この検証環境のネットワークポリシーでは `huggingface.co` への到達が `403 Forbidden` でブロックされており、モデル重みの実ダウンロードは確認できなかった（`torch` 本体のインストール自体はPyPI標準indexから可能。専用index `download.pytorch.org` も同様に403でブロックされたため使用していない）。別環境でHugging Face Hubへ到達可能であれば、この先のモデルロード〜生成まで進められる見込み。
- **ヘッドレスE2E（録音済みwav→文字起こし→ChatGPT応答→音声生成）**：`OPENAI_API_KEY` がSecret Store未設定のため、ChatGPT応答生成の工程をAI単独では実行できない（True Human Gate、Notion `AFP-01-T02-A` のBlocker参照）。ローカルWhisperのみでの文字起こし自体は依存関係が揃えば動作する見込みだが、上記のモデル重みダウンロード制約もあり、本タスクのAI実行範囲では実施していない。

## 現在の状態

2026-09-09 JST: 初期PoCコードを Experimental に登録。
2026-09-10 JST: Codexレビュー指摘（`share=True`の公開共有リンク、声クローンがプロセスグローバルで複数セッション間に漏れる問題、生成物の出力先が`.gitignore`のスコープ外になり得る問題）を修正し、この安全設計の前提（`share=False`・声データの利用者ごとの分離）をコードへ反映済み。次の工程は本人同意UI・AI明示表示（Notion `AFP-01-T01`）と実機検証。
2026-09-11 JST: Notion `AFP-01-T01` を実施。声クローンプロンプト（旧 `active_voice.pt`）・応答音声（旧 `response.wav`）の両方について、プロセスグローバル／固定パスへの永続保存をやめ、システム一時ディレクトリへ発行する一意なファイルパスとして `gr.State`（セッションごとに独立）にのみ保持するよう変更。起動時に過去の声クローンを自動ロードする挙動も廃止した。声登録タブに本人同意チェックボックス（必須）と「AIによる合成音声である」旨の明示表示を追加し、未同意では登録が進まないようにした。対話モード切り替え時に会話履歴（`Chatbot`表示・ChatGPTへ渡す履歴の両方）をリセットし、モード間で履歴が混在しないようにした。`share=False`は維持。次の工程はNotion `AFP-01-T02`（実機・実音声環境での検証）。
2026-09-13 JST: Notion `AFP-01-T02-A`（AI実行範囲: 依存関係インストール検証・`requirements.txt`整備・README起動手順確定）を実施。`requirements.txt` を新規作成し、クリーンなvenvでの依存関係インストールを検証した。ヘッドレスE2E本体（ChatGPT応答生成を含む）は `OPENAI_API_KEY` 未設定（True Human Gate）に加え、この検証環境ではHugging Face Hubへの到達もネットワークポリシーでブロックされているため、AI単独では完了できないことを確認した。次の工程はNotion側でSecret Store経由の `OPENAI_API_KEY` 設定（Human）、およびHugging Face Hubへ到達可能な環境でのモデルロード〜ヘッドレスE2E本体の実施。
