# LLM 自動採点スクリプト

学生が提出した PDF レポートから考察箇所を自動抽出し、採点基準に基づいて LLM が評価するスクリプトです。

## 仕組み

1. **フェーズ1 ― 考察抽出**: PDF 全文を LLM に渡し、学生自身の考察・分析文のみを抽出する（コード・数値表・問題文は除外）。
2. **フェーズ2 ― 採点**: 抽出した考察を採点基準と照合し、各基準を ○ / △ / × で評価してコメントと総評を生成する。

---

## セットアップ

### 1. ツールのインストール

`make` が必要です。未インストールの場合は以下でインストールしてください。

```bash
conda install -n base -c conda-forge make
```

その後、以下を実行するだけで conda 環境 `llm-grader` が作成され、必要なパッケージがすべてインストールされます。

```bash
make setup
```

インストールされるもの：
- Python 3.11 + 全依存パッケージ
- Tesseract OCR（日本語データ含む）
- Playwright ブラウザ

> **注意**: 環境は `miniconda3/envs/llm-grader/` に作成されます。管理者権限は不要です。

### 2. 環境の有効化

採点実行前に conda 環境を有効化してください。

```bash
conda activate llm-grader
```

### 3. データの準備

`data/` フォルダに以下の3つを用意してください。

| ファイル / フォルダ | 置き場所 | 内容 |
|------------------|---------|------|
| 提出フォルダ | `data/submissions/` | 学生ごとにサブフォルダを作り、その中に PDF を置く |
| 採点基準 | `data/rubric.txt` | 評価ポイント・模範解答テキスト |
| 採点割り当て表 | `data/assignment.xlsx` | 列「提出者　氏名」と「採点者」を持つ Excel |

```
data/submissions/
  田中　太郎_レポート/
    report.pdf
  鈴木　花子_レポート/
    report.pdf
```

採点割り当て表の形式：

| 提出者　氏名 | 採点者 |
|------------|--------|
| 田中　太郎 | 採点者１ |
| 鈴木　花子 | 採点者２ |

> 氏名のスペースは全角・半角どちらでも照合できます。

### 4. 認証情報

高田研の Qwen 35B モデルを利用するために配布されているユーザー名・パスワードを使います。パスワードはコマンドライン引数には渡せず、実行時にターミナルで入力します（入力中は画面に表示されません）。環境変数 `LLM_PASS` に設定することも可能です。

```
$ python src/grade.py --backend ui --ui-user ユーザー名 --evaluator "採点者名"
UI password:    ← ここで入力（非表示）
```

---

## 使い方

**担当分のみ採点する場合**

```bash
python src/grade.py --backend ui --ui-user ユーザー名 --evaluator "採点者名"
```

**全学生を採点する場合**

```bash
python src/grade.py --backend ui --ui-user ユーザー名
```

**画像ベースの PDF が含まれる場合（OCR 高速化）**

考察が末尾に書かれている課題では `--ocr-pages` で OCR 対象を末尾 N ページに限定できます。

```bash
python src/grade.py --backend ui --ui-user ユーザー名 --ocr-pages 3
```

---

## 出力

`result/` フォルダに以下のファイルが保存されます。

| ファイル | 内容 |
|---------|------|
| `*_grades.csv` | 生の採点結果（中間ファイル） |
| `*_grades.xlsx` | 色分けされた Excel |

**Excel の構成**

シート1「採点結果」― 行は割り当て表の順でソート済み

| 列 | 内容 |
|---|------|
| No. | 通し番号 |
| 学生名 | 提出者氏名 |
| 採点者 | 担当採点者名（割り当て表から自動取得） |
| 基準1 | ○ / △ / × の記号（○=緑・△=黄・×=赤） |
| 基準1 判断理由 | LLM が生成した1文のコメント |
| 基準2 | ○ / △ / × の記号（○=緑・△=黄・×=赤） |
| 基準2 判断理由 | LLM が生成した1文のコメント |
| 総評 | LLM が生成した総合評価（2文以内） |
| 抽出した考察 | フェーズ1で LLM が抽出した考察文 |

シート2「採点基準」― `data/rubric.txt` の内容をそのまま掲載

---

## オプション一覧

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--submissions-dir DIR` | `data/submissions` | 学生の提出フォルダ |
| `--rubric-file FILE` | `data/rubric.txt` | 採点基準テキストファイル |
| `--assignment-file FILE` | `data/assignment.xlsx` | 採点割り当て Excel |
| `--evaluator NAME` | （全員） | 指定した採点者の担当学生のみ処理 |
| `--output-dir DIR` | `result` | 出力ディレクトリ |
| `--ui-url URL` | （設定済み URL） | Web UI の URL |
| `--ui-user USER` | （入力プロンプト） | UI ログインユーザー名（環境変数 `LLM_USER` でも可） |
| `--ocr-pages N` | `0`（全ページ） | OCR 対象を末尾 N ページに限定（画像 PDF の高速化） |
| `--no-excel` | — | Excel 出力をスキップ |

---

## ファイル構成

```
src/
  grade.py          メインスクリプト（採点実行）
  excel_report.py   CSV → Excel 変換
  pdf_extractor.py  PDF テキスト抽出・OCR フォールバック
  llm_client.py     LLM バックエンド（Web UI）
data/               ← gitignore 済み（個人情報を含むため）
  submissions/
  rubric.txt
  assignment.xlsx
result/             ← gitignore 済み
Makefile
requirements.txt
README.md
```
