# SKILL: リリース作業

企業経営シミュレーションの新バージョンをリリースするときの手順。
配布物フォルダの作成・Word資料の生成・コミット・PRマージまでを一括で行う。

---

## トリガー

ユーザーが以下のような指示を出したとき：
- 「v0.9.Xをリリースしたい」
- 「デリバラブルに入れて」
- 「リリース作業をやって」

---

## 実行手順

### 1. バージョン番号を確認する

`index.html` 冒頭の `APP_VERSION` を確認する。

```bash
grep "APP_VERSION" MitsunoriKomaba/management-simulation/index.html | head -3
```

ユーザーが明示した場合はその番号を使う。

---

### 2. index.dist.html を再生成する

```bash
cd MitsunoriKomaba/management-simulation
node -e "
const fs = require('fs');
const Babel = require('/tmp/node_modules/@babel/standalone');
const html = fs.readFileSync('index.html', 'utf8');
const scriptMatch = html.match(/<script type=\"text\/babel\">([\s\S]*)<\/script>\s*<\/body>/);
const result = Babel.transform(scriptMatch[1], {
  presets: [['react', {runtime: 'classic'}]],
  filename: 'app.js'
});
let newHtml = html
  .replace('<script src=\"https://unpkg.com/@babel/standalone/babel.min.js\"></script>', '')
  .replace(/<script type=\"text\/babel\">([\s\S]*)<\/script>(\s*<\/body>)/, '<script>' + result.code + '</script>\$2');
fs.writeFileSync('index.dist.html', newHtml, 'utf8');
console.log('Done. Size:', fs.statSync('index.dist.html').size, 'bytes');
"
```

※ `@babel/standalone` が `/tmp/node_modules/` にない場合は `npm install --prefix /tmp @babel/standalone` で導入する。

---

### 3. deliverablesフォルダを作成し、HTMLを格納する

```bash
VERSION=v0.9.X  # 実際のバージョン番号に置き換える
mkdir -p MitsunoriKomaba/management-simulation/deliverables/$VERSION
cp MitsunoriKomaba/management-simulation/index.html MitsunoriKomaba/management-simulation/deliverables/$VERSION/
cp MitsunoriKomaba/management-simulation/index.dist.html MitsunoriKomaba/management-simulation/deliverables/$VERSION/
```

---

### 4. はじめてガイド（Word版）を生成する

`README.md` の内容を元に、既存フォーマット（`#0D9488` ティール・`#0F172A` ダークネイビー）でWordファイルを生成する。

- 参照ファイル：`README.md`
- 出力先：`deliverables/$VERSION/はじめてガイド_$VERSION.docx`
- フォーマット参照：`deliverables/v0.9.6/はじめてガイド_v0.9.6.docx`

python-docxを使って生成する。フォーマットの詳細は既存ファイルから読み取ること。

---

### 5. リリースノート（Word版）を生成する

`CHANGELOG.md` の内容を元に、PR/FAQ形式でWordファイルを生成する。

- 参照ファイル：`CHANGELOG.md`、`design-doc.md`
- 出力先：`deliverables/$VERSION/リリースノート_前バージョン-$VERSION.docx`
- フォーマット参照：`deliverables/v0.9.6/リリースノート_v0.9.1-v0.9.6.docx`
- 構成：PR（旧新比較表）→ 全バージョン変更履歴 → FAQ

FAQは変更内容から自然に生まれる疑問を5問程度生成する。

---

### 6. コミット・PR作成・マージ

```bash
git checkout -b feature/claude-release-$VERSION
git add MitsunoriKomaba/management-simulation/deliverables/$VERSION/
git add MitsunoriKomaba/management-simulation/index.dist.html
git commit -m "chore: $VERSION リリース配布物を追加"
git push -u origin feature/claude-release-$VERSION
```

PRを作成してmainにsquash mergeする。

---

## 成果物チェックリスト

リリース完了時に以下が揃っていることを確認する：

- [ ] `deliverables/$VERSION/index.html`
- [ ] `deliverables/$VERSION/index.dist.html`
- [ ] `deliverables/$VERSION/はじめてガイド_$VERSION.docx`
- [ ] `deliverables/$VERSION/リリースノート_*.docx`
- [ ] `index.dist.html`（ルートの配布用ファイルも最新版に更新済み）
- [ ] PRがmainにマージ済み

---

## 注意事項

- `index.dist.html` はBabel事前コンパイル済みの配布用ファイル。`index.html` をそのまま配布しないこと
- Wordファイルのフォーマットは必ず既存ファイルから読み取って踏襲すること（カラーコード・フォントサイズ・テーブルスタイル）
- `CHANGELOG.md` と `design-doc.md` の変更履歴・既知の課題を参照して、リリースノートのFAQに反映すること
