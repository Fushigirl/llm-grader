@echo off
chcp 65001 > nul
echo ============================================
echo  LLM 自動採点スクリプト セットアップ
echo ============================================
echo.

echo [1/3] Python パッケージをインストール中...
pip install -r requirements.txt
if errorlevel 1 (echo. & echo [エラー] pip install に失敗しました & pause & exit /b 1)

echo.
echo [2/3] Playwright ブラウザをインストール中...
playwright install chromium
if errorlevel 1 (echo. & echo [エラー] playwright install に失敗しました & pause & exit /b 1)

echo.
echo [3/3] Tesseract OCR を確認中...
where tesseract >nul 2>&1
if %errorlevel% == 0 (
    echo Tesseract はインストール済みです。スキップします。
    goto done
)

echo Tesseract をインストール中（管理者権限が必要です）...
winget install --id UB-Mannheim.TesseractOCR -e --accept-source-agreements --accept-package-agreements
if errorlevel 1 (echo. & echo [エラー] Tesseract のインストールに失敗しました & pause & exit /b 1)

echo 日本語データをダウンロード中...
powershell -Command "Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tessdata/raw/main/jpn.traineddata' -OutFile 'C:\Program Files\Tesseract-OCR\tessdata\jpn.traineddata'"
if errorlevel 1 (echo. & echo [エラー] 日本語データのダウンロードに失敗しました & pause & exit /b 1)

:done
echo.
echo ============================================
echo  セットアップ完了！
echo ============================================
pause
