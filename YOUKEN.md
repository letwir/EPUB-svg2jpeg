**要件定義書 (YOUKEN)**

- **目的**: AozoraEpub由来のEPUB内で外部SVG参照が表紙として無視される問題を解決するため、EPUB内の外部SVG画像をJPEG(ラスタ)に変換し、XHTML内の参照を置換してEPUBを再生成する。

- **対象ファイル形式**: EPUB3 のみ。

- **入力**: 
  - CLI: `convert.py -i <入力ファイルまたはディレクトリ>`。
  - ディレクトリ指定時は内部の `*.epub` を再帰検索して処理する。

- **出力**:
  - CLI: `convert.py -o <出力ファイルまたはディレクトリ>`。
  - ディレクトリ指定時は `-i` で見つけた EPUB 群を同名で出力ディレクトリへ保存。
  - 出力 EPUB は元と同名（上書きまたは別フォルダ）、画像は `.jpeg` に置換。

- **画像変換仕様**:
  - 変換対象: (EPUBファイル)/item/xhtml/cover.xhtmlに埋め込まれたsvgタグを変換し、(EPUBファイル)/item/images/cover.jpegへ保存。
  - cover.xhtmlは放置して、"item\standard.opf"ファイルを操作する。id="cover-page"タグの内容を以下にする。
  content.opf_sampleが変換元のファイルサンプル。
```before
<manifest>
<item href="Text/cover.xhtml" id="cover.xhtml" media-type="application/xhtml+xml" properties="svg"/>
```
↓
```after
<manifest>
<item href="images/cover.jpeg" id="cover" media-type="image/jpeg"/>
```

  - 出力画像: JPEG
    - ピクセル寸法: 幅 1,600 px × 高さ 2,560 px（縦横比 1.6:1）
    - 解像度: 72 dpi
    - JPEG 品質: 100
    - プログレッシブ: 無効
    - カラーモード: RGB（サブサンプリング無しを目標。実装は使用ライブラリの仕様に従う）
  - 変換後: 元の `.svg` は削除し、同名で `.jpeg` を配置（表紙等の重複は上書き）。

- **XHTML / OPF の書き換え**:
  - XHTML 内の参照は拡張子のみ置換（例: `images/foo.svg` → `images/foo.jpeg`）。
  - `content.opf`（manifest）などのメディアタイプ参照も自動更新する。

- **実行環境 / 言語 / 実行方式**:
  - 言語: Python 3（Ubuntu 26.04 を想定、WSL での検証可）。
  - 並列性: 1 EPUB ファイル = 1 スレッド（`-j` でスレッド数指定）。
  - 圧縮: 再生成する EPUB は Python 標準の `zipfile` を使用し、最大圧縮を適用する。`mimetype` は無圧縮で ZIP の先頭に格納すること。

- **CLI オプション**:
  - `-i, --input <path>`: 入力 EPUB ファイルまたはディレクトリ
  - `-o, --output <path>`: 出力 EPUB ファイルまたはディレクトリ
  - `-j, --jobs <n>`: 並列に処理する EPUB の数（デフォルト: 1）
  - `--timeout <秒>`: EPUB 個別処理のタイムアウト（デフォルト: 300 秒）

- **エラーハンドリング / 再試行**:
  - 個別 EPUB の処理で失敗した場合はスキップして次へ進む（リトライ無し）。
  - タイムアウトは 300 秒（5 分）。

- **ログ / 出力**:
  - 標準出力へワンラインログを出力: `input: <path>, output: <path>, status: OK|NG skip`。
  - 詳細ログは出力しない（要件通り）。

- **パフォーマンス要件**:
  - 処理速度目標は無し。並列化は EPUB 毎に行うのみ。

- **セキュリティ**:
  - 特別なセキュリティ要件無し。

- **制約 / 注意点**:
  - EPUB は EPUB3 のみ対応。
  - `mimetype` を ZIP 内の先頭に非圧縮で配置すること（EPUB 規格準拠）。
  - SVG に外部フォント参照や外部リソースがある場合は、そのまま変換結果に影響する可能性がある。`cover.xhtml` に埋め込まれた inline SVG は変換対象とする。

- **テスト / 受け入れ基準**:
  - 単体テストを作成し、自動化されたテストで合否判定する。
  - サンプルデータ: 最小サンプル EPUB（外部 SVG を含む）、期待出力 EPUB を用意する。

- **運用 / デプロイ**:
  - CLI ツールとして配布。
  - ドキュメントは `README.md` に記載。
  - ライセンス: GPLv3。

- **追加の実装メモ**:
  - 画像変換は ImageMagick / rsvg-convert / CairoSVG 等いずれかを利用可能にする（Python バインディングを推奨）。
  - JPEG 生成時に「サブサンプリング無し（4:4:4）」を指定できるライブラリ設定を優先する。
