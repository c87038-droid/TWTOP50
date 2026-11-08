台股市值前50大｜手機網頁版（新增本益比）
===================================

【本次修改】
本益比顯示在每張股票卡片的「股價／漲跌幅」下面，並在資料說明顯示本益比日期。
CSV 新增本益比(倍)、本益比資料日；其他 50 大、均線、警示、漲跌停功能不變。
本益比使用 TWSE／TPEx 最新官方收盤估值，不會因盤中每15秒刷新而變成即時本益比。
沒有值時顯示「—」，來源失敗不阻擋股價排行榜。

【如果 GitHub 已有舊程式】
1. 登入 https://github.com/ ，打開自己的 taiwan-top50 Repository。
2. 更新兩個檔案：app.py 和 market_data.py（檔名大小寫完全一致）。
3. requirements.txt 無需變更。Commit changes 提交更新。
4. 已部署 Streamlit 的話，等待其自動重新部署或在 App 管理頁面重新啟動。
5. 開啟你的 streamlit.app 網站，確認股票卡片多了「本益比」。

【如果 GitHub 還沒部署成功】
1. 新增公開 GitHub Repository（例如 taiwan-top50）。
2. 將 app.py、market_data.py、requirements.txt 三個檔案直接上傳到 Repository 根目錄（不要上傳 ZIP）。
3. 登入 https://share.streamlit.io/ 並用 GitHub 帳號授權。
4. 選擇建立 App：Repository＝你的帳號/taiwan-top50；Branch＝main；Main file＝app.py。
5. 按 Deploy，成功後會取得可從 iPhone／Android 瀏覽器開啟的網址。
6. iPhone Safari 可選「分享→加入主畫面」。

【重要】
尚未替你直接發布網站；必須在 GitHub／Streamlit 完成部署後才能用手機網址打開。
程式邏輯與 CSV 已通過離線測試，官方資料連線仍需部署後驗證。
TWSE／TPEx 有可能短暫拒絕雲端 IP；若只缺本益比，排行榜仍可運作。
