"""PyInstaller / 源码通用入口: python run.py 或打包后的可执行文件。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from copyany.main import main

if __name__ == "__main__":
    raise SystemExit(main())
