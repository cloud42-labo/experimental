# 未来の店舗生存サバイバルゲーム — Design Doc（実装ベース・改訂版）

> **改訂の経緯**: 本書は当初 `store-survival-simulator-spec.md`（インセプションデッキ＆PRD）を
> ベースに、SpatiaLite + FastAPI + MapLibre/D3.js という技術スタックを前提とした実装設計書
> だった。実装は`store-survival-game-gdd-v6.md`（GDD v6.1）が示す「円建て財務モデルを持たない
> 定性診断」という方向性は踏襲しつつ、GDDが提案したStreamlit/PyDeck/標準SQLiteでもなく、
> 旧spec/design-docが前提としたSpatiaLite/FastAPIでもない、**バックエンド・DBを一切持たない
> 単一HTML構成**に落ち着いた。研修配布用途（「HTMLファイル単体で配布し、参加者ごとに自分の
> e-Stat APIキーでデータ取得する」）に合わせて、一度は境界データも含め全データをライブ取得する
> 設計を試みたが、**実機検証の結果、境界データの配信元がブラウザからのCORSを一切許可しない
> ことが判明**したため、境界ポリゴンのみ静的に同梱し、人口統計データだけを参加者のAPIキーで
> ライブ取得するハイブリッド方式に落ち着いた。本書はその最新の実装を記述したものである
> （経緯の詳細は `README.md` を参照）。

---

## 1. アーキテクチャ概要

```mermaid
flowchart TD
    A["起動画面でユーザーが\ne-StatアプリケーションIDを入力"] --> C
    B["INAGE_BOUNDARY\n(HTMLに同梱済みの境界ポリゴン)"] --> D
    C["ブラウザが直接fetch:\ngetStatsData ×4 (e-Stat API)"] --> D["ブラウザ内で突合・\nコーホート変化率を計算"]
    D --> E["INAGE_GEOJSON (メモリ上のみ)"]
    E --> F["Leaflet.js + Turf.jsで描画"]
```

サーバー・データベースは存在しない。`prototype.html` はローカルファイルとして開くだけで
動作する。起動直後の画面でユーザーが**自分自身のe-Stat アプリケーションID（APIキー）**を
入力すると、ブラウザがそのキーを使って直接 `api.e-stat.go.jp` にfetchし、人口統計データを
その場で取得する。キーはJS変数として保持されるのみで、`localStorage`等への永続化や配布
ファイルへの埋め込みは行わない。取得した統計データもページを閉じれば消える（キャッシュしない）。

町丁目の境界ポリゴン（地図の形状データ）はAPIキーを使わず、`INAGE_BOUNDARY`という
HTML内に静的に埋め込まれたJS定数から読む（下記参照）。

> ✅ **CORS実機検証済み（2026-07-26、Chrome、`file://`で開いた状態）**:
> - `api.e-stat.go.jp/rest/3.0/app/json/getStatsData` … ブラウザから正常にfetchできる
>   ことを確認（実際のappIdでレスポンスが返り、Console上でも`No 'Access-Control-Allow-Origin'`
>   等のエラーは出ない）。
> - `www.e-stat.go.jp/gis/statmap-search/data`（境界shapefileの配信元） … **CORSで
>   確実にブロックされる**。Consoleに `Access to fetch at '...' from origin 'null' has
>   been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present on
>   the requested resource.` と明示的に出る。サーバー側がCORSヘッダーを一切返さない
>   仕様であり、クライアント側の実装では回避不可能（プロキシを挟む以外の解決策はない）。
>
> この検証結果に基づき、境界ポリゴンの取得はライブfetchをやめ、静的同梱に戻した
> （下記「境界データの扱い」参照）。

### 境界データの扱い（`INAGE_BOUNDARY`、静的同梱）
`scripts/download_boundary.py` → `scripts/build_geojson.py` で事前生成した
`data/inage_ku.geojson` から、`geometry` と `properties.key_code` / `properties.name`
だけを抜き出した軽量版を、`prototype.html` 内に `const INAGE_BOUNDARY = {...}`として
直接埋め込んである（人口等の統計値プロパティは含まない。それらは起動時に毎回ライブ
取得するため、古い数値を埋め込んでおく意味がないから）。他エリアへ展開する場合は、
これらのスクリプトの`WARD_CODE`/`PREF_CODE`を変更して作り直し、この定数を差し替える。

---

## 2. データ取得ロジック（`prototype.html` 内、`loadRealData()`）

対象は千葉市稲毛区（`WARD_CODE=12103`）固定。ゲーム開始ボタン押下時に、以下を**逐次**fetchする
（並列化していない。理由は`getStatsData`側の同時アクセス数を抑えるため）。

| 用途 | 取得元 | 統計表ID/パラメータ |
| :--- | :--- | :--- |
| 町丁目境界ポリゴン | `INAGE_BOUNDARY`（HTML内に静的同梱、APIキー不要・fetchなし） | `key_code`が`12103`始まりの地物のみ抽出 |
| 男女別人口総数・世帯総数（令和2年） | `getStatsData`（ライブfetch） | `8003006730` |
| 年齢（5歳階級）別人口（令和2年） | `getStatsData`（ライブfetch） | `8003006752` |
| 世帯の家族類型別一般世帯数（令和2年） | `getStatsData`（ライブfetch） | `8003006873` |
| 年齢（5歳階級）別人口（平成27年、コーホート変化率算出用） | `getStatsData`（ライブfetch） | `8003000081` |

処理の流れ（`loadRealData()` → 各ヘルパー関数）:
1. `loadBoundaryFeatures()`: `INAGE_BOUNDARY.features`から稲毛区（`key_code`が`12103`始まり）
   のみを同期的にフィルタする（fetchなし）。
2. `fetchStatsTable()`: `getStatsData`（`searchKind=2`, `cdAreaFrom/cdAreaTo`で稲毛区に絞込）を
   呼び出し、`RESULT.STATUS !== 0`ならAPIキー誤り等としてエラーを投げる。
3. `areaLevels()`: `CLASS_INF.CLASS_OBJ`から町丁目レベル（level 2/4）の地域コードと名称を抽出。
4. 年齢階級を3区分（`pop_young`=15-24歳, `pop_active`=25-59歳, `pop_senior`=60歳以上＋65歳以上
   ロールアップ）に集約。
5. 2015年・2020年の同一区分人口から、町丁目ごとの年率変化率を算出:
   $$\text{rate}_b = \left(\frac{\text{Pop}_{2020}(b)}{\text{Pop}_{2015}(b)}\right)^{1/5} - 1$$
   （年齢シフトを追うコーホート要因法ではなく、同一区分同士の単純比較の簡易版）
6. 2015年データが無い／0の町丁目は、区全体の人口加重平均レート（フォールバック）で補完する。
7. `INAGE_BOUNDARY`側の`key_code`と統計値の地域コードを突合し、`geometry` + `properties`
   （`population`, `households_total`, `pop_young/active/senior`, `rate_young/active/senior`,
   `family_hh`, `senior_hh` 等）を持つ`INAGE_GEOJSON`（メモリ上のグローバル変数）を組み立てる。

各`getStatsData`呼び出しは`try/catch`で失敗を捕捉し、起動画面に「取得に失敗しました: (理由)」
を表示して再試行できるようにする。DBスキーマは存在せず、町丁目1件＝GeoJSON Feature 1件が
そのまま最終データであり、正規化されたリレーショナルモデルは使っていない。

---

## 3. フロントエンドUI（`prototype.html`）

単一のHTMLファイルで、外部依存はCDN経由の **Leaflet.js 1.9.4** と **Turf.js 6** のみ
（MapLibre/D3.js、Streamlit/PyDeckのいずれも不使用。境界データを静的同梱に戻したため、
shapefile ZIPをブラウザで解凍・変換するための`shpjs`も不要になり削除した）。

### 3.0 起動画面（`#setupScreen`）
ページを開くと最初に表示される画面。ゲームタイトル・概要説明、e-Stat APIキー入力欄
（`type=password`、表示/隠すトグル付き）、開始ボタンのみで構成される。開始ボタン押下で
`loadRealData()`が完了すると`#setupScreen`を隠し、`#gameRoot`（地図・診断UI一式）を表示する
（`rerenderAll()`はこの成功後にのみ呼ばれる。データ未取得の間は空振りするようガードしてある）。

### 3.1 商圏抽出
店舗位置（クリック）を中心に、業種ごとの `radiusDefault`（500m〜3000m）を半径として、
Turf.jsで町丁目ポリゴンとの交差判定を行い、商圏内フィーチャー集合を得る。

### 3.2 業種定義（`BUSINESS_TYPES`）
GDD v6.1と同じ7業種を実装済み（コンビニ／食品スーパー／居酒屋／ドラッグストア／
ペットショップ・サロン／ペット関連小売／金融事業・地域代理店）。各業種は
`weights`（若年/現役/シニアの客層適性重み）、`laborDependency`（依存する労働力層）、
`wasteRiskCoef`（商品ミスマッチ感度）、`radiusDefault` を持つ。**円建ての初期売上・
原価率・人件費率はGDD文書上「参考値」として残っているだけで、コードには一切存在しない。**

### 3.3 戦略適合度診断（`evaluateStrategy()`）
実人口データのみを使い、円換算は行わない。

* **客層マッチ度**: 業種の重み × 商圏内実人口（3区分）を現在・10年後で比較した比率。
* **採用のしやすさ**: 依存する労働力層の人口が10年でどう変わるかの比率
  （`laborPoolAt()`。ヒトコマンド「主婦・シニア短時間シフト」適用時は労働力プールの
  定義を切り替える）。
* **商品ミスマッチ判定**: 高齢化率30%超 かつ 業種が若年/現役寄りの場合にフラグを立てる
  （モノコマンドで解消可能）。
* **判定は3段階**: `ratio >= 1.0` → 良好、`>= 0.8` → 注意、それ未満 → 深刻
  （GDD v6.1の本文が挙げる4段階・閾値1.1/0.9/0.7とは異なる、実装上の簡易版）。

**カネ（財務）コマンドは実装されていない**（GDD v6.1の「一旦削除」方針をそのまま反映）。

### 3.4 未実装のGDD要素
以下はGDD v6が描いていたが、プロトタイプには実装されていない:
* Streamlit + PyDeckによる3D描画、標準SQLite + JISメッシュ座標計算
* 10期（10年間）のP&L推移シミュレーション
* SSS〜Eの生存ランク判定
* ポータブルZIP配布（`起動する.bat` / `run.sh`）

---

## 4. 対応範囲・制約

* 対象エリアは千葉市稲毛区固定（`WARD_CODE`はHTML内にハードコード、境界データも
  稲毛区分のみ同梱）。他エリア対応には`scripts/`での境界データ再生成＋
  `INAGE_BOUNDARY`定数の差し替え、およびUIでの地域選択が必要。
* 境界データの年度またぎ対応（市町村合併・字の変更によるKEY_CODE不整合）は未対応。
  現状は2020年境界固定・2015年との単純区分比較のみ。
* 境界ポリゴンは同梱データのため常に最新の行政区画変更を反映できるとは限らない
  （更新には`scripts/`の再実行＋手動での定数差し替えが必要）。
* 人口統計データはページ滞在中のみメモリに保持され、リロードすると再取得が必要
  （オフライン再開・キャッシュの仕組みはない）。
* APIキーの検証はe-Stat側のエラーレスポンス（`RESULT.STATUS`）任せで、事前のフォーマット
  チェック等は行っていない。

## 5. 未解決事項（Open Questions）

* 町丁目の年度またぎ対応（新旧KEY_CODE対応）は必要になった時点で検討。
* 稲毛区以外への展開時、`WARD_CODE`のハードコードと境界データ再生成の手順をどう
  簡略化するか。
* GDD v6.1が言及する「実データ化された場合の財務シミュレーション復活」を実装するかどうかは未定。
* 研修中に多数の参加者が同時に`getStatsData`を叩くことによる、e-Stat側のレート制限・
  負荷への配慮は未検討（1参加者あたり4リクエスト×同時多数、という規模感の想定のみ）。
* `api.e-stat.go.jp`のCORS許可は2026-07-26時点の実機確認に基づく。将来e-Stat側の
  仕様変更でブロックされるようになった場合、境界データと同様に静的同梱へ戻すか、
  プロキシを検討する必要がある。
