"""庫存盤點系統啟動入口。

本機：  python run_stocktake.py        → http://127.0.0.1:5001
部署：  gunicorn run_stocktake:app
"""

import os

from stocktake.app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEBUG")))
