# Safe Minimal Wallet Writer — 仕様書

## 1. 概要

本リポジトリは、**1台の iPhone・1枚の既知 Wallet カード・1枚のローカル画像** を対象に、Apple Wallet のカード背景を書き換える最小 CLI ツールである。

fork 元の GUI、パスコードテーマ、テレメトリ、更新確認は**含まない**。
CARD_ID 取得は **読取専用** の `scan.py` のみ提供する。

---

## 2. 独立性

### 2.1 元コードからの依存

| 項目 | 状態 |
|---|---|
| `aircard.py` / `aircard_backend.py` / `apply_card_skin.py` | **不使用・削除済み** |
| `AirCardApp.swift` | **不使用・削除済み** |
| 親 `Sources/` 参照 | **なし** |
| 実行時 import | **Python 標準ライブラリのみ** |
| 外部 Python パッケージ | **なし** |
| 事前ビルド済みバイナリ同梱 | **なし** |

実行に必要なソースは **`safe_minimal/` 以下だけ** で完結する。

```
safe_minimal/
├── flash.py
├── Makefile
├── Sources/
│   ├── device_bridge.m
│   ├── airtraffic_bridge.m
│   └── airlift_target.h
├── tests/
└── bin/                 # make で生成（Git 管理外）
```

### 2.2 残る外部依存（意図的）

| 依存 | 用途 |
|---|---|
| macOS `python3` | CLI 実行 |
| macOS `/usr/bin/sips` | 画像リサイズ・PDF 変換 |
| `MobileDevice.framework` | USB 経由の iPhone 通信 |
| `AirTrafficHost.framework` | Books 同期プロトコル |
| `xcrun clang` | ローカルビルド |

**インターネット通信は行わない。** 通信先は接続中の iPhone のみ。

---

## 3. スコープ

### 3.1 含む機能

- UDID・カード ID・画像パスを引数で受け取る
- 画像を Wallet 用アセット（PNG×2 + PDF）に変換
- `.pkpass` 内のアートワークを書き込む
- `.cache` / `.pkcache` のレンダリング済み顔を**実削除**する
- Books 同期状態のスナップショット取得と復元

### 3.2 含まない機能

- 端末一覧・自動検出
- GUI
- 複数カード一括処理
- カード ID の永続保存
- パスコードテーマ（`.passthm`）
- HTTP / テレメトリ / 更新確認

---

## 4. CLI 仕様

### 4.1 flash.py

```sh
cd safe_minimal
make
./flash.py <UDID> <CARD_ID> /absolute/path/to/image.png
```

| 引数 | 形式 | 説明 |
|---|---|---|
| `UDID` | `[A-Fa-f0-9-]{8,64}` | USB 接続中 iPhone の UDID |
| `CARD_ID` | `[-A-Za-z0-9_+=]{16,64}` | Wallet カード識別子 |
| `image` | ローカルファイルパス | 入力画像 |

### 4.2 scan.py（読取専用）

```sh
./scan.py <UDID>
./scan.py <UDID> --timeout 60 --json
```

| 引数 | 説明 |
|---|---|
| `UDID` | USB 接続中 iPhone の UDID |
| `--timeout` | 秒数指定。省略時は Enter まで待機 |
| `--json` | 検出 ID を JSON で stdout に出力 |

`scan.py` は `log_bridge` 経由で `com.apple.os_trace_relay` を読み、
`/Passes/Cards/{CARD_ID}.pkpass` 等のパスから CARD_ID を抽出する。
iPhone への書込みは行わない。

### 4.3 終了コード

| コード | 意味 |
|---|---|
| `0` | 成功 |
| `1` | 端末チェック失敗、書込み失敗、キャッシュ削除失敗 |
| `2` | 引数不正、ヘルパーバイナリ未ビルド |

### 4.4 成功後のユーザー操作

Wallet アプリを強制終了し、再起動する。反映されない場合は iPhone を再起動する。

---

## 5. 処理フロー

```text
flash.py
  │
  ├─ [1] probe              … 端末接続・互換性確認
  ├─ [2] prepare_assets     … sips で PNG(1536×969) + PDF 生成
  ├─ [3] write_assets       … .pkpass へ 3 ファイル書込
  ├─ [4] remove_cache_files … .cache  の FrontFace/PlaceHolder/Preview 削除
  └─ [5] remove_cache_files … .pkcache も同様
```

各書込み・削除操作は次の安全手順を必ず踏む。

1. `snapshot-books` — iPhone の Books 状態を Mac 側 temp に保存
2. `stage` — StreamingZip と Books.plist を端末へ配置
3. `airtraffic_bridge` — AirTraffic 同期でファイル移動
4. `finish-write` または `finish-moved-removal` — 後始末と Books 復元

---

## 6. 端末パス

| 用途 | パス |
|---|---|
| パス本体 | `/var/mobile/Library/Passes/Cards/{CARD_ID}.pkpass` |
| レンダリングキャッシュ | `/var/mobile/Library/Passes/Cards/{CARD_ID}.cache` |
| 代替キャッシュ | `/var/mobile/Library/Passes/Cards/{CARD_ID}.pkcache` |

### 6.1 書き込むアセット

| ファイル名 | 内容 |
|---|---|
| `cardBackgroundCombined@3x.png` | 1536×969 PNG |
| `cardBackgroundCombined@2x.png` | 同上 |
| `cardBackgroundCombined.pdf` | PNG から sips 変換した PDF |

### 6.2 削除するキャッシュファイル

| ファイル名 | 理由 |
|---|---|
| `FrontFace` | 表示中の顔画像 |
| `PlaceHolder` | プレースホルダ |
| `Preview` | プレビュー |

**上書きではなく unlink（AirTraffic 経由の move）が必須。** バイト列の上書きでは iOS 27 以降で古い画像が残る。

---

## 7. ネイティブコンポーネント

### 7.1 `device_bridge`

**ソース:** `safe_minimal/Sources/device_bridge.m`  
**フレームワーク:** `MobileDevice.framework`

#### 許可コマンド（これ以外は拒否）

| コマンド | 引数 |
|---|---|
| `probe` | `<udid>` |
| `snapshot-books` | `<udid> <snapshot_dir>` |
| `stage` | `<udid> <source> <link> <recovered> <zip> <books.plist> <snapshot_dir>` |
| `finish-write` | `<udid> <source> <link> <recovered> <snapshot_dir>` |
| `finish-moved-removal` | `<udid> <source> <link> <recovered> <snapshot_dir> <count>` |

#### 接続ポリシー

- USB 直接接続のみ（`directConnectionsOnly: YES`）
- Wi-Fi ペアリング端末の探索は無効

#### 成功判定（Python 側 `operation_ok`）

```
exitCode == 0
AND targetGatePassed == true
AND operation.ok == true
```

### 7.2 `airtraffic_bridge`

**ソース:** `safe_minimal/Sources/airtraffic_bridge.m`  
**フレームワーク:** `AirTrafficHost.framework`

#### 引数

```sh
airtraffic_bridge <udid> <asset_id> <destination> [<asset_id> <destination> ...]
```

#### プロトocol

1. `SyncAllowed` 待機
2. HostInfo 送信（`SyncHostName: safe-local-wallet`）
3. `ReadyForSync` 待機
4. `AssetManifest` 取得・検証
5. `SendAssetCompleted` で各アセットを移動

---

## 8. セキュリティ境界

### 8.1 実行可能ファイルの制限

`flash.py` の `run_json()` は次の 2 バイナリのみ実行を許可する。

- `safe_minimal/bin/device_bridge`
- `safe_minimal/bin/airtraffic_bridge`

加えて `/usr/bin/sips` のみを画像処理に使用する。

### 8.2 禁止事項（ソース監査対象）

Makefile `audit` ターゲットが以下の存在を拒否する。

- HTTP クライアント（URLSession, curl, requests 等）
- 任意シェル実行（system, popen）
- 動的ライブラリロード（dlopen）
- 任意 socket 通信

### 8.3 Mac から外部へ出るデータ

**インターネットには送信しない。**

iPhone へ送るデータ:

1. 変換済みカード画像（PNG / PDF）
2. ランダム生成された staging 名を含む Books 同期メタデータ
3. AirTraffic 同期メッセージ

Mac に残る一時データ:

- Books スナップショット（`tempfile` 配下、処理後削除）
- 画像変換用 temp（処理後削除）

### 8.4 永続保存

本ツールはカード ID・UDID・画像・ログを**永続保存しない**。

---

## 9. 安全不変条件

以下は省略不可。

1. **毎操作前に `snapshot-books`** — Books  preimage を取得
2. **`stage` 前にスナップショット一致確認** — 端末状態が変わっていれば中止
3. **`finish-*` で必ず Books 復元** — 失敗時も復元を試行
4. **staging 名は `secrets.token_hex(10)` で生成** — 固定パスを使わない
5. **キャッシュは AirTraffic move で削除** — AFC 直接削除は使わない
6. **各操作は独立した token / snapshot** — 1 回の flash で最大 3 操作（write + cache×2）

---

## 10. ビルドとテスト

### 10.1 ビルド

```sh
cd safe_minimal
make        # audit + compile + ad-hoc sign
```

### 10.2 テスト

```sh
cd safe_minimal
make test   # unittest 4件 + py_compile
```

### 10.3 生成物

| 出力 | 説明 |
|---|---|
| `bin/device_bridge` | 端末 AFC / staging ヘルパー |
| `bin/airtraffic_bridge` | AirTraffic 同期ヘルパー |

`bin/` は `.gitignore` 対象。使用前に必ずローカルビルドすること。

---

## 11. 互換性

`airlift_target.h` に記載の iOS ビルドは `TargetGate` で検証済みとして扱う。

```
iOS 27.0 / 24A435
iOS 27.0 / 24A437
iOS 27.0 / 24A5390f
```

未検証ビルドでも gate は通過するが、動作保証はない。

---

## 12. 旧 fork との関係

| 観点 | 説明 |
|---|---|
| 実行時依存 | **なし** — 旧 Python / Swift / 親 Sources は参照しない |
| アルゴリズム | Airlift 方式を踏襲（Books snapshot → stage → sync → finish） |
| コード由来 | `device_bridge.m` は fork 版を最小化して `safe_minimal/Sources/` に内包 |
| 監査 | 旧版にインターネット送信は見つかっていないが、本版は機能をさらに削減 |

本仕様書は **`safe_minimal/` 現行構成** を正とする。旧 `docs/` 配下の設計資料は obsolete。

---

## 関連ドキュメント

- 実行手順: [`safe-minimal-runbook.md`](safe-minimal-runbook.md)
