# Safe Minimal Wallet Writer — 実行手順書

本書は [`safe-minimal-spec.md`](safe-minimal-spec.md) に基づき、実際にカード画像を適用するまでの手順を説明する。

---

## 1. 事前準備

### 1.1 必要なもの

| 項目 | 内容 |
|---|---|
| Mac | macOS（Xcode Command Line Tools インストール済み） |
| iPhone | USB ケーブルで接続可能、Mac とペアリング済み |
| UDID | 対象 iPhone の UDID（事前に控える） |
| CARD_ID | 対象 Wallet カードの識別子（事前に控える） |
| 画像 | ローカル PNG / JPEG など（任意サイズ可） |

### 1.2 本ツールが自動で行わないこと

- iPhone の自動検出
- カード ID の自動取得
- 複数カードの一括処理

**UDID と CARD_ID は実行前に自分で用意する。**

### 1.3 iPhone 側の状態

実行前に以下を確認する。

1. iPhone の画面ロックを解除する
2. 「このコンピュータを信頼しますか？」が出ていれば **信頼** を選ぶ
3. USB ケーブルで Mac に接続する（Wi‑Fi 同期のみは使わない）
4. Wallet に対象カードが登録済みであること

---

## 2. 初回ビルド

リポジトリを取得済みであることを前提とする。

```sh
cd /path/to/AirCard/safe_minimal
make
```

成功すると次が生成される。

```text
safe_minimal/bin/device_bridge
safe_minimal/bin/airtraffic_bridge
```

### 2.1 ビルド確認

```sh
ls -l bin/device_bridge bin/airtraffic_bridge
./flash.py --help
```

両バイナリが `-rwx` で存在し、`--help` が表示されれば OK。

### 2.2 任意: テスト実行

```sh
make test
```

4 件の unittest が PASS すればよい。iPhone 接続は不要。

---

## 3. UDID の確認

本ツールには端末一覧機能がない。次のいずれかで UDID を確認する。

### 方法 A: Finder

1. iPhone を USB 接続
2. Finder 左ペインの iPhone を選択
3. 機種名の下をクリックして **シリアル番号 ↔ UDID** を切り替え
4. UDID をコピー

### 方法 B: システム情報

```sh
system_profiler SPUSBDataType | grep -A 5 "iPhone"
```

表示された Serial Number が UDID の場合がある。Finder 方式の方が確実。

---

## 4. CARD_ID の確認

CARD_ID は Wallet 内部のカード識別子（Base64 風の文字列）である。

例:

```text
M6nDwZrkYbFlsodLgCbvyFZQ1cc=
```

### 4.1 スキャナで取得（推奨）

`scan.py` は **読取専用** で、USB 経由のデバイスログから CARD_ID を抽出する。
iPhone への書込みは行わない。

```sh
cd safe_minimal
make
./scan.py "<UDID>"
```

手順:

1. iPhone を USB 接続し、画面ロックを解除する
2. 上記コマンドを実行する
3. iPhone でサイドボタン2回 → Face ID → 対象カードをタップする
4. ターミナルに `Detected card [1]: ...` と表示された ID を控える
5. 終わったら Enter を押す

タイムアウト指定:

```sh
./scan.py "<UDID>" --timeout 60
```

JSON 出力:

```sh
./scan.py "<UDID>" --timeout 60 --json
```

**コンソール.app だけでは CARD_ID が出ないことがある。** 本スキャナは
`os_trace_relay` 経由で `/Passes/Cards/...pkpass` パスを拾う。

### 4.2 既知 ID を使う

- 以前の fork 版や別ツールで取得済みの ID を使う
- 自分で調査・記録しておいた ID を使う

CARD_ID が不明な場合、**flash.py だけでは実行できない**。

---

## 5. 画像の準備

入力画像はローカルファイルであればよい。ツール側で次の変換を行う。

- 1536 × 969 PNG へリサイズ
- 同名 PDF へ変換

推奨:

- 横長画像（カード比率に近いもの）
- ファイル名に空白が多い場合はパスを引用符で囲む

例:

```sh
IMAGE="/Users/you/Pictures/wallet-skin.png"
```

---

## 6. 実行

### 6.1 基本コマンド

```sh
cd /path/to/AirCard/safe_minimal

./flash.py \
  "<UDID>" \
  "<CARD_ID>" \
  "/absolute/path/to/image.png"
```

具体例:

```sh
./flash.py \
  "00008120-001A1D0A1EE9A01E" \
  "M6nDwZrkYbFlsodLgCbvyFZQ1cc=" \
  "/Users/you/Pictures/my-card.png"
```

### 6.2 実行中の処理

ツールは内部で次を順に行う。

1. 端末互換性チェック（`probe`）
2. 画像変換（`sips`）
3. `.pkpass` へアートワーク書込
4. `.cache` のキャッシュ削除
5. `.pkcache` のキャッシュ削除

通常 1〜3 分程度。処理中は iPhone を切断しない。

### 6.3 成功時の表示

```text
Done. Force-close Wallet on the iPhone, then reopen it.
```

---

## 7. iPhone 側の確認

### 7.1 必須操作

1. Wallet アプリを**アプリスイッチャーから完全終了**
2. Wallet を再起動
3. 対象カードを開いて背景が変わっているか確認

### 7.2 反映されない場合

1. iPhone を再起動
2. 再度 Wallet を開く
3. それでも変わらない場合は「9. トラブルシュート」を参照

---

## 8. 終了コード

| コード | 意味 | 対処 |
|---|---|---|
| `0` | 成功 | 7章の確認へ |
| `1` | 端末/書込/キャッシュ削除失敗 | 9章を参照 |
| `2` | 引数不正 or 未ビルド | UDID/CARD_ID/画像パス確認、`make` 再実行 |

---

## 9. トラブルシュート

### `error: ... is missing; run make`

```sh
cd safe_minimal
make
```

### `error: invalid UDID` / `error: invalid card ID`

- UDID: 英数字とハイフンのみ、コピーミスがないか確認
- CARD_ID: 16〜64 文字、`../` などパス文字が混ざっていないか確認

### `error: device compatibility check failed`

1. iPhone のロック解除
2. 「このコンピュータを信頼」を再確認
3. USB ケーブル差し直し
4. 別 USB ポートを試す
5. iPhone 再起動

### `error: artwork write failed`

1. CARD_ID が対象カードと一致しているか確認
2. iPhone の空き容量を確認
3. 画像ファイルが読めるか確認
4. 再実行

### `error: could not clear .cache` / `.pkcache`

1. 一度 Wallet を完全終了
2. 同じコマンドを再実行
3. 改善しない場合は iPhone 再起動後に再実行

### 画像が古いまま

1. Wallet 完全終了 → 再起動
2. iPhone 再起動
3. CARD_ID が別カードの ID になっていないか確認

---

## 10. 再実行・やり直し

同じ CARD_ID に別画像を適用する場合:

1. 新しい画像パスを用意
2. 同じ `./flash.py` コマンドを再実行する

CARD_ID や UDID が同じなら、追加設定は不要。

---

## 11. クリーンビルド

問題切り分け時:

```sh
cd safe_minimal
make clean
make
make test
```

---

## 12. セキュリティ上の注意

- 本ツールはインターネット送信を行わない
- 実行可能ファイルは `bin/device_bridge` と `bin/airtraffic_bridge` のみ
- バイナリは必ず自分で `make` して生成したものを使う
- 他人が配布した `bin/` をそのまま使わない

詳細は [`safe-minimal-spec.md`](safe-minimal-spec.md) の「セキュリティ境界」を参照。

---

## 13. クイックリファレンス

```sh
# 初回
cd safe_minimal && make

# 実行
./flash.py "<UDID>" "<CARD_ID>" "/path/to/image.png"

# 成功後（iPhone）
# Wallet を完全終了 → 再起動
```
