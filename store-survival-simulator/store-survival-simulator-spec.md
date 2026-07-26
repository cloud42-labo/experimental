# 未来の店舗生存シミュレーター（仮称）
## プロジェクト憲章（インセプションデッキ）＆ 製品要件定義書（PRD）

本ドキュメントは、e-Stat APIより取得可能な町丁目レベル（小地域統計・地域メッシュ）の実データを活用し、店舗小売業向けに出店戦略のみならず、将来の商圏変化予測（生存シミュレーション）および労働需要・店舗運営改善のシミュレーションを行うアプリケーションの開発仕様書である。

---

# 第1部：インセプションデッキ（Inception Deck）

## 1. 我々はなぜここにいるのか（Why We Are Here）
日本の店舗小売業は、急激な**「人口減少・高齢化による商圏の縮小」**と**「深刻な人手不足（採用難・人件費高騰）」**という二大構造的課題に直面している。
従来の出店戦略ツールは、出店時点での「静的な商圏データ」を可視化するに留まり、「出店から5年後、10年後にその店舗が生き残れるか」「地域の労働力が枯渇した際にオペレーションをどう変えるべきか」という未来の動的シミュレーション機能が著しく欠如していた。
本プロジェクトは、**e-Statが提供する信頼性の高いオープンデータ（国勢調査・経済センサス等）を活用し、店舗の未来の生存率を予測し、持続可能な店舗経営（ターゲットのシフト・働き方の改革）を導くための意志決定支援ツール**を提供する。

## 2. エレベーターピッチ（The Elevator Pitch）
*   **【顧客】** 10年先を見据えて新規出店や店舗改革を行いたい店舗小売業のオーナーや開発担当者、人事マネージャー向け
*   **【課題】** 出店後に商圏の人口が激変し業績が下落することや、人手不足でシフトが埋まらず黒字廃業に追い込まれるリスクを避けたい
*   **【製品名】** 未来の店舗生存シミュレーター（仮称）
*   **【主要価値】** 町丁目レベルの実統計データに基づき、将来の顧客ボリュームの減衰推移と、周辺競合を踏まえた「アルバイト採用難易度」を予測する。
*   **【対抗馬】** 一般的なGIS商圏分析ソフト（高額であり、静的な現在の人口可視化に留まる）
*   **【差別化要素】** 10年後の商圏生存予測に加え、「シニアシフト時の売上改善度」や「日中短時間シフト導入による採用費削減効果」といった店舗運営の**具体的変革効果（働き方改革シミュレーション）**を提示・予測できる点。

## 3. パッケージデザイン（Product Packaging）
*   **キャッチコピー**: 「出店から10年。あなたの店舗は、誰を雇用し、誰に売って生き残りますか？」
*   **メインビジュアル**: 地図上に描かれた店舗の円（商圏）。5年後、10年後の時系列バーをスライドすると、周辺の町丁目の色が変わり（若年世代の減少・高齢化）、採用費の予測値が赤（警告）へと変化する。
*   **バリュープロポジション**:
    *   **生存予測シミュレーション**: 10年間の売上減退率を予測。
    *   **採用難易度マップ**: 周辺町丁目の「潜在労働人口」と、経済センサスに基づく「周辺競合店」を掛け合わせて採用リスクを指数化。
    *   **処方箋シミュレーション**: 営業時間変更やシフト形態の多様化（主婦・シニア雇用）による採用コスト削減効果を提示。

## 4. やらないことリスト（The NOT List）
開発スコープを限定し、本質的な価値提供を最速で達成するため、以下の境界線を設ける。
*   **やるべきこと（IN）**
    *   e-Stat API（バージョン3.0）から小地域（町丁目）および1km/500mメッシュデータの自動取得。
    *   過去の国勢調査データ比較に基づく、町丁目別の人口・世帯数構成変化の予測シミュレーション。
    *   競合事業所数（経済センサス）と労働人口を掛け合わせた採用難易度インデックスの算出。
    *   店舗オーナーが入力した条件（営業時間、時給、ターゲット層）に基づくシミュレーションエンジンの開発。
*   **絶対にやらないこと（OUT）**
    *   GPS等によるリアルタイムの人流データや動的な自動車交通量データの自社取得（高額なコストを避けるため、オープンデータで代替）。
    *   完全な自動売上予測（個別店舗のMD力やブランド力に過度に依存するため、あくまで「商圏購買力」のシミュレーションに留める）。
    *   求人媒体への直接自動出稿・応募管理機能（ATS機能）。

## 5. ご近所さんを探せ（Your Neighbors）
本アプリのステークホルダーと期待される連携関係：
*   **店舗開発担当者 / フランチャイズ本部**: 出店妥当性の評価やFC加盟検討者への説得資料として使用。
*   **店舗オーナー / エリアマネージャー**: 既存店舗の業績低下に対するターゲットの切り替え（品揃えシフト）の判断。
*   **人事・採用担当者**: 採用難易度の高い店舗の特定、時給設定やシフト条件見直しのための客観データ取得。
*   **政府・自治体（e-Stat提供側）**: 正しいオープンデータ利活用の実例提供、クレジット表記の遵守。

## 6. 技術的な解決策（Technical Solution）
*   **フロントエンド**: 
    *   **MapLibre GL JS / Mapbox GL JS**: 地図描画・操作用の高性能ライブラリ。
    *   **D3.js**: SVG/GeoJSONを活用した空間データの軽量可視化（D3のスケール機能による色の割り当て）。
*   **バックエンド**:
    *   **Python (FastAPI / Bottle)**: e-Stat APIとの連携、データクレンジング、空間集計。
*   **データベース**:
    *   **SpatiaLite (SQLiteの空間情報拡張)**: 軽量かつオープンソースの空間データベース。ポリゴンデータのR-Index（空間インデックス）を活用した店舗半径内町丁目の高速交差演算。

## 7. 夜も眠れなくなるような問題（What Keeps Us Awake at Night）
*   **e-Stat APIのパフォーマンス懸念**: 描画のたびにAPIを直接叩くと、極めて遅い。
    *   *対策*: APIから取得した地域統計データおよびGIS境界ポリゴンは一度 **SpatiaLiteデータベースに永続化** してキャッシュし、アプリからはローカルDBからGeoJSONを出力する構成とする。
*   **フロントエンドの描画負荷（メモリクラッシュリスク）**: 町丁目ポリゴン（SVGのpath要素）が数千個にのぼると、ブラウザでの描画やスクロールが著しく重くなる。
    *   *対策*: メッシュ表示時は、一般的なSVGの `path` による複雑な境界描画ではなく、**`rect`（矩形）要素**でグリッド描画する技術を採用し、DOMノードの描画負荷を低減する。

---

# 第2部：製品要件定義書（PRD）

## 1. ユーザーペルソナとユースケース

### ペルソナA：佐藤 健二（45歳・中堅ドラッグストアの店舗開発部長）
*   **ゴール**: 出店候補地の選定。3年後に競合が激化したり、10年後に周辺がシニアばかりになって「ファミリー向け中大型店」が維持できなくなるリスクを避けたい。
*   **ユースケース**: 地図上の候補地をクリックし、半径1kmの「10年後顧客推移」を確認。ファミリー世帯の減少を検知し、「10年後にシニア特化型（介護・健康食品中心）店舗に移行可能な店舗設計にする」ための説得材料にする。

### ペルソナB：田中 美咲（34歳・居酒屋チェーンの人事・採用マネージャー）
*   **ゴール**: 深夜ワンオペ問題や、バイトが集まらず休業に追い込まれる事態の回避。
*   **ユースケース**: 既存の「深夜営業型居酒屋（若者バイト依存）」の店舗エリアの採用難易度を分析。5年後に若年人口が半減することを知り、「22時閉店・日中パート（主婦・シニア）中心」のシフト構成に変えた場合の採用ポテンシャルの変化をグラフで確認する。

---

## 2. システムアーキテクチャとデータフロー

システムは、政府統計の総合窓口(e-Stat)が提供するWeb API(バージョン3.0)と、取得した空間統計データを高速に処理するためのSpatiaLiteデータベース、Webサーバー、ブラウザ側クライアントで構成される。

### データ取得と永続化の全体図
1.  **初回またはバッチ処理**:
    *   アプリがe-Stat APIの `getStatsList` で特定の地域（都道府県単位等）の統計ID一覧を取得する。
    *   各統計IDに対し `getStatsData` APIを実行し、統計データを取得。
    *   データベース（SpatiaLite）に、属性データ（年齢別、世帯別構成など）と、対応する地理情報ポリゴン（MapArea）を変換してインポート・格納する。
2.  **クライアントからのWebリクエスト**:
    *   ユーザーが地図上で特定の範囲（バウンディングボックス：北端・南端・東端・西端の緯度経度）を指定。
    *   Webサーバー（Python）はSpatiaLiteから範囲内（または交差する）の町丁目データを、SQLの `AsGeoJson()` 関数を使ってGeoJSONとして高速に抽出し、クライアントへ返す。
3.  **クライアント側の軽量描画**:
    *   フロントエンド（D3.js）は、受信したGeoJSONデータを地図上にマージして色塗り（階級区分）描画を行う。

---

## 3. データベース設計（SpatiaLite）

e-Statから取得する膨大なデータを、商圏・採用難易度の切り口で瞬時に集計するため、以下のテーブルスキーマを定義する。

### 3.1 統計メタデータ：`Stat`
統計調査の概要（例：令和2年国勢調査、平成26年経済センサス等）を格納する。

| カラム名 | データ型 | キー | 説明 |
| :--- | :--- | :--- | :--- |
| `stat_id` | TEXT | PRIMARY KEY | 統計情報のID（e-Stat上のキー） |
| `stat_name` | TEXT | | 政府統計名 |
| `stat_name_code` | TEXT | | 政府統計名コード |
| `gov_org` | TEXT | | 作成機関名 |
| `gov_org_code` | TEXT | | 作成機関名コード |
| `survey_date` | TEXT | | 調査実施日 |
| `title` | TEXT | | 統計表の表題 |

### 3.2 統計値データ：`StatValue`
各エリアおよび各集計項目における統計の生数値を保持する。

| カラム名 | データ型 | キー | 説明 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | PRIMARY KEY (AUTOINCREMENT) | レコード固有の一意ID |
| `stat_id` | TEXT | FOREIGN KEY (Stat.stat_id) | 対象の統計情報ID |
| `value` | TEXT | | 統計の値（人口数、世帯数、事業所数など） |

### 3.3 属性メタデータ：`StatValueAttr`
統計値が「どの属性（例：男性、20〜24歳、ファミリー世帯など）」に紐づいているかを定義する。

| カラム名 | データ型 | キー | 説明 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | PRIMARY KEY (AUTOINCREMENT) | 属性値固有の一意ID |
| `stat_id` | TEXT | FOREIGN KEY (Stat.stat_id) | 対象の統計情報ID |
| `stat_value_id` | INTEGER | FOREIGN KEY (StatValue.id) | 紐づく統計値ID |
| `attr_name` | TEXT | | 属性名（例：`"age"`, `"sex"`, `"household_type"`） |
| `attr_value` | TEXT | | 属性値（例：`"20_24"`, `"female"`, `"family"`） |

### 3.4 ジオメトリデータ：`MapArea`
町丁目（または地域メッシュ）のポリゴン（空間情報）を格納する。

| カラム名 | データ型 | キー | 説明 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | PRIMARY KEY (AUTOINCREMENT) | 地理データの一意ID |
| `stat_id` | TEXT | FOREIGN KEY (Stat.stat_id) | 対象の統計情報ID |
| `stat_val_attr_id` | INTEGER | FOREIGN KEY (StatValueAttr.id) | 紐づく属性ID |
| `geometry` | POLYGON | (SpatiaLite Geometry) | 各地域の地理的境界を定義する多角形情報 |

#### 🛠️ SpatiaLiteの初期化と空間インデックスの定義（Python実装例）
ジオメトリ列およびインデックス（R-Tree）は通常のSQLite/ORM機能だけでは生成できないため、データベース初期化時に以下のSQL文を直接実行して初期設定を行う。

```python
import sqlite3

def init_spatial_db(db_path, spatialite_lib_path):
    conn = sqlite3.connect(db_path)
    # SpatiaLite拡張のロード
    conn.enable_load_extension(True)
    conn.load_extension(spatialite_lib_path)
    
    cursor = conn.cursor()
    # 空間メタデータテーブルの初期化
    cursor.execute("SELECT InitSpatialMetadata();")
    
    # 1. ジオメトリ列を含まないベースのテーブル作成
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS MapArea (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stat_id TEXT,
        stat_val_attr_id INTEGER
    );
    """)
    
    # 2. AddGeometryColumnを用いたPolygon列の追加 (SRID 4326: WGS84測地系)
    cursor.execute("""
    SELECT AddGeometryColumn('MapArea', 'geometry', 4326, 'POLYGON', 'XY');
    """)
    
    # 3. 高速検索用の空間インデックス（R-Treeインデックス）の作成
    cursor.execute("""
    SELECT CreateSpatialIndex('MapArea', 'geometry');
    """)
    
    conn.commit()
    conn.close()
```

---

## 4. e-Stat API 連携仕様

町丁目レベル（小地域集計・地域メッシュ統計）をプログラムから自動取得するためのAPI呼び出し規約。

### 4.1 基本リクエストURL（JSON形式）
```http
https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData?[パラメータ群]
```

### 4.2 必須・推奨パラメータ
町丁目・地域メッシュデータを抽出する際は、以下の構成でAPIリクエストを実行する。

*   **`appId`**: e-Statのマイページから発行した「アプリケーションID（通称APIキー）」。
*   **`statsDataId`**: 取得対象の特定の統計表ID。
*   **`searchKind`**: **`2`を指定すること（必須）**。
    *   *重要*: 通常の統計APIでは膨大な小地域・メッシュデータは除外されます。`searchKind=2` を指定することで、町丁目やメッシュ情報が検索対象に含まれます。
*   **`limit`**: データ取得制限件数。デフォルトは最大100,000件に設定を推奨（小地域データはサイズが大きいため）。

#### 🌐 PythonによるAPIデータ取得とメッシュ緯度経度変換（コード例）
e-Statの地域メッシュデータには、座標値が直接含まれていない（メッシュコードのみ）。そのため、`python-geohash` などのライブラリ、またはメッシュコード変換ルールを用いて経度・緯度の範囲（Polygonの4つ角）を算出してデータベースに格納する。

```python
import urllib.request
import urllib.parse
import json
# 1kmメッシュコードから緯度経度の境界（Polygon）を計算するロジック例
def meshcode_to_polygon_wkt(meshcode):
    """
    1次〜3次メッシュコード（数値テキスト）をSpatiaLiteに挿入可能な WKT (Well-Known Text) 形式に変換。
    """
    meshcode = str(meshcode)
    # 第1次基準地域メッシュ（4桁）
    p = int(meshcode[0:2])
    u = int(meshcode[2:4])
    lat_min = p / 1.5
    lng_min = u + 100
    
    lat_max = lat_min + (40 / 60) # 40分
    lng_max = lng_min + 1.0       # 1度
    
    # 第2次地域メッシュ（+2桁: 6桁）
    if len(meshcode) >= 6:
        q = int(meshcode[4])
        v = int(meshcode[5])
        lat_min += q * (5 / 60)   # 5分
        lng_min += v * (7.5 / 60) # 7.5分
        lat_max = lat_min + (5 / 60)
        lng_max = lng_min + (7.5 / 60)
        
    # 第3次地域メッシュ / 1kmメッシュ（+2桁: 8桁）
    if len(meshcode) >= 8:
        r = int(meshcode[6])
        w = int(meshcode[7])
        lat_min += r * (30 / 3600)  # 30秒
        lng_min += w * (45 / 3600)  # 45秒
        lat_max = lat_min + (30 / 3600)
        lng_max = lng_min + (45 / 3600)
        
    # SpatiaLiteに流せる WKT Polygon 文字列に成形
    wkt = (f"POLYGON(({lng_min} {lat_min}, "
           f"{lng_max} {lat_min}, "
           f"{lng_max} {lat_max}, "
           f"{lng_min} {lat_max}, "
           f"{lng_min} {lat_min}))")
    return wkt

# e-Stat APIから小地域・メッシュ統計データをフェッチする
def fetch_estat_mesh_data(app_id, stats_data_id):
    base_url = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"
    params = {
        "appId": app_id,
        "statsDataId": stats_data_id,
        "searchKind": "2", # 小地域・地域メッシュ必須
        "limit": "100000"
    }
    url = base_url + "?" + urllib.parse.urlencode(params)
    
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode("utf-8"))
        return data
```

---

## 5. シミュレーションモデルの計算ロジック

本アプリのコアバリューである、「ターゲットシフト」と「働き方シフト」の2つのシミュレーションを裏付ける計算ロジック。

### 5.1 【ターゲットシフト】商圏購買力＆売上予測減退モデル

店舗オーナーは、自店の「現在のメイン客層（属性 $T_0$ ）」と「現在の売上 $R_{now}$ 」を入力する。

1.  **商圏抽出**:
    ユーザーが指定した店舗座標 $(y, x)$ から半径 $D$ (km) のバッファを生成し、空間データベースの R-Index を用いて、交差する全町丁目（または地域メッシュ） $M$ の集合 $S = \{m_1, m_2, ..., m_k\}$ を抽出する。
2.  **基準客層世帯数の集計 ($H_{now}$)**:
    現在の商圏内におけるターゲット客層の総世帯数（または人口）を集計。
    $$H_{now} = \sum_{i \in S} \text{StatValue}(i, T_0)$$
3.  **1世帯あたり年間購買貢献額 ($C$) の基準化**:
    $$C = \frac{R_{now}}{H_{now}}$$
4.  **10年後のターゲット数減少の予測 ($H_{future}$)**:
    過去の国勢調査データ（例：令和2年と平成27年など）の増減トレンド、および年齢スライド（例：5歳階級移動による若年世帯の高齢化）を加味したターゲット自然増減率 $\alpha$ から、10年後の世帯数 $H_{future}$ を算出。
    $$H_{future} = H_{now} \times (1 + \alpha)^{10}$$
5.  **自然減衰時の10年後予測売上 ($R_{future}^{decay}$)**:
    $$R_{future}^{decay} = H_{future} \times C$$
    *(ここで「品揃えやターゲットを何もしないままだと、売上は $R_{now} - R_{future}^{decay}$ 減退する」という警告を出す)*
6.  **シニアシフト（ターゲット変更 $T_{new}$ ）による売上回復シミュレーション**:
    店主が「シニア向けMD（ $T_{new}$ ）に転換する」を選択した場合。
    *   10年後のシニア世帯数 $H_{future\_senior} = \sum_{i \in S} \text{StatValue}(i, T_{new}) \times (1 + \beta)^{10}$
    *   シニア世帯の購買単位額 $C_{senior}$ （家計調査の平均品目購入額等、または基準Cの一定比率）を掛け合わせ、新たな将来売上ポテンシャルを再提示する。
    $$R_{future}^{new} = H_{future\_senior} \times C_{senior}$$

---

### 5.2 【働き方シフト】採用難易度＆採用コスト削減モデル

深夜営業・若手アルバイト（15〜24歳）依存のオペレーション（働き方 $W_0$ ）から、主婦・シニアが短時間で働くオペレーション（働き方 $W_{new}$ ）へシフトした際の効果を予測。

1.  **求職潜在ターゲット人口の算出**:
    *   **現在の若者労働力 ($L_{young}$)**: 商圏 $S$ 内の「15〜24歳の人口」
    *   **主婦・非正規潜在労働力 ($L_{shufu}$)**: 商圏 $S$ 内の「30〜49歳女性のうち非労働力人口または短時間就業者」
    *   **シニア労働力 ($L_{senior}$)**: 商圏 $S$ 内の「60〜69歳の人口」
2.  **採用競合店舗数 ($C_{comp}$)**:
    商圏 $S$ 内における経済センサス「小売業（中分類56〜60）および飲食サービス業（中分類76）」の総事業所数を抽出。
    $$C_{comp} = \sum_{i \in S} \text{事業所数}(i, \text{Retail/Food})$$
3.  **採用難易度インデックス ($Idx_{hire}$)**:
    ターゲット求職者人口を競合店舗数で除した、店舗あたりの求職ターゲットアロケーション率。
    $$Idx_{hire}(W) = \frac{\sum L_{target}(W)}{C_{comp}}$$
    *(このインデックスが閾値を下回る店舗は「採用危機・休業リスクあり」とマップ上で赤く強調される)*
4.  **「働き方改革」時給・採用コスト削減シミュレーション**:
    *   **現状維持 ($W_0$)**: 募集時給を競合ひしめく中で高止まりさせないと若者が集まらず、求人媒体への掲載頻度 $N$ が増えるため、年間採用費 $Cost_{young} = \text{時給}_{high} \times \text{人数} + N \times 50,000$ 円とする。
    *   **シフト多様化導入 ($W_{new}$)**: 短時間勤務、深夜営業なしの主婦・シニア雇用。採用母集団 $Idx_{hire}$ が格段に緩和されるため、標準時給での採用が可能になり、近隣の口コミやポスティングで直接応募が増加し、媒体掲載費が大幅削減。
    $$\text{削減効果額} = Cost_{young} - Cost_{new}$$
    を算出。オーナーへ「働き方を変えれば、年間〇〇万円の採用コストが浮き、シフト充足率は〇%上がります」という提案をダッシュボードに出力する。

---

## 6. フロントエンド・空間データ描画要件（D3.js & Web）

ブラウザ上で何千もの町丁目ポリゴンをスムーズに描写し、スライドバーによる年度切り替えにミリ秒単位で追従するためのフロントエンド要件。

### 6.1 ポリゴン描画のパフォーマンス最適化技術（SVG rect）
地図上に大量の町丁目データを可視化する際、一般的なSVGの `<path>` 要素に複雑な境界座標（GeoJSON）をそのまま描画すると、数千のDOMノードがメモリを逼迫させ、ズーム・スクロール時に画面がカクつく致命的なバグの原因になる。

地域メッシュ（1km/500mメッシュ）は定義上**「必ず四角形（グリッド）」**である。
したがって、D3.jsでの描画時は、複雑なパス計算を行う `d3.geoPath()` の使用を避け、**SVGの `<rect>`（矩形）要素** として座標をマッピングして一括描画する。

#### 💻 D3.jsによる軽量メッシュ描画コード例
```javascript
// D3.jsを用いた地域メッシュ（rect）の高速レンダリング例
function renderMeshGrid(svgElement, geoJsonData, width, height) {
    const svg = d3.select(svgElement);
    
    // メルカトル投影法の適用（空間座標からピクセルへの変換）
    const projection = d3.geoMercator()
        .fitSize([width, height], geoJsonData);
        
    // 塗り分けスケールの作成（例：人口数0〜5000人を青〜濃赤にグラデーション）
    const colorScale = d3.scaleLinear()
        .domain([0, 1000, 3000, 5000])
        .range(["#e0f7fa", "#4fc3f7", "#ffb74d", "#e53935"]);

    // geoJsonの各フィーチャーから、4つ角の範囲（バウンディングボックス）を取得してrectを配置
    svg.selectAll("rect")
        .data(geoJsonData.features)
        .enter()
        .append("rect")
        .attr("x", d => {
            // 左上の経度・緯度を取得してピクセルx座標に投影
            const bounds = d3.geoBounds(d); // [[lng_min, lat_min], [lng_max, lat_max]]
            const topLeft = projection([bounds[0][0], bounds[1][1]]);
            return topLeft[0];
        })
        .attr("y", d => {
            const bounds = d3.geoBounds(d);
            const topLeft = projection([bounds[0][0], bounds[1][1]]);
            return topLeft[1];
        })
        .attr("width", d => {
            const bounds = d3.geoBounds(d);
            const topLeft = projection([bounds[0][0], bounds[1][1]]);
            const bottomRight = projection([bounds[1][0], bounds[0][1]]);
            return Math.abs(bottomRight[0] - topLeft[0]);
        })
        .attr("height", d => {
            const bounds = d3.geoBounds(d);
            const topLeft = projection([bounds[0][0], bounds[1][1]]);
            const bottomRight = projection([bounds[1][0], bounds[0][1]]);
            return Math.abs(bottomRight[1] - topLeft[1]);
        })
        .attr("fill", d => colorScale(d.properties.value)) // 統計値に連動してカラーリング
        .attr("opacity", 0.75)
        .on("mouseover", function(event, d) {
            d3.select(this).attr("opacity", 1.0);
            // ツールチップ表示ロジック（properties.valueなどを表示）
        })
        .on("mouseout", function(event, d) {
            d3.select(this).attr("opacity", 0.75);
        });
}
```

---

## 7. 開発・検証フェーズ定義（QAテスト基準）

エンジニアが本番デプロイ前にクリアすべき検証項目。

1.  **APIパラメータ検証**: e-Stat APIリクエストのURLパラメータに `searchKind=2` が正しく指定され、戻り値のJSONに小地域/地域メッシュ（町丁目の階層構造）が含まれていること。
2.  **空間クエリの速度検証**: 地図上の1クリックに対して、半径1km内の町丁目を SpatiaLite で検索し、交差集計・GeoJSON返却までの時間が **150ms以内** であること（R-Index空間インデックスが機能しているか）。
3.  **描画パフォーマンス検証**: 1画面内に1,000件以上のメッシュポリゴンを描画した状態で、ズームイン・アウトの操作時にFPSが **45以上** を維持できていること（`rect`要素等による軽量描画の動作検証）。
4.  **クレジット表示検証**: 成果物のアプリケーション画面内の目立つ箇所（または利用情報部分）に、e-Stat APIの利用規約に準じたクレジット表示（例：「このサービスは、政府統計APIを利用して開発されていますが、サービスの内容は国によって保証されたものではありません。」）が正しく実装されていること。
