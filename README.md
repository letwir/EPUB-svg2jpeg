# EPUBの表紙svgファイルをjpgに変換して最大圧縮で再生成するスクリプト


## 使い方
convert.py -i hoge.epub -o hoge2.epub
のように使います。
フォルダ指定の場合

convert.py -i hoge/*.epub -o hoge2/
のように指定します。

## 仕様
EPUBファイルをtmpフォルダに展開し、表紙のSVGファイルをjpg 100%で変換します。
その後、xhtmlのsvg部分をjpgへと書き換え、EPUBファイルを再圧縮します。
