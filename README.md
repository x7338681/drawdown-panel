# 從高點回撤買進｜0050 / 比特幣

靜態網頁，可放在 GitHub Pages。每天自動抓最新收盤價並重算統計。

## 網址怎麼開

1. 在 GitHub 新增一個公開 repo（例如 `drawdown-panel`）
2. 把這個資料夾全部檔案推上去（`index.html` 要在 repo 根目錄）
3. Settings → Pages → Source 選 **GitHub Actions** 或 **Deploy from a branch**（branch: `main`，folder: `/root`）
4. 幾分鐘後網址會是：

`https://你的帳號.github.io/drawdown-panel/`

## 自動更新

`.github/workflows/update.yml` 每天 19:00（台灣）跑一次：

- 0050：證交所日成交
- 比特幣：Yahoo `BTC-USD`

跑完會 commit `data.json`。你重新整理網頁就是最新。

也可在 Actions 頁按 **Run workflow** 立刻更新。

## 本機預覽

不要直接雙擊 `index.html`（fetch 會失敗）。在這個資料夾執行：

```bash
python3 -m http.server 8080
```

瀏覽器開 http://127.0.0.1:8080

手動更新資料：

```bash
pip install -r requirements.txt
python scripts/update.py
```

## 統計定義

每一波從當時歷史高點往下，只記「第一次」碰到門檻。

- 0050：−10% / −20% / −30%，資料自 2003-06-30
- 比特幣：−30% / −40% / −50%，資料自 2014-09-17

1 年／3 年平均只用已經滿期的那幾次，不含配息。
