"""命令行入口。

用法:
  copyany            启动(已运行则改为显示面板)
  copyany --show     通知已运行的实例显示面板(用于桌面环境自定义快捷键)
  copyany --selftest 运行核心功能自检(源码环境)
  copyany --debug    调试日志输出到控制台
"""
from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler

from . import __version__, config


def _parse_args(argv):
    p = argparse.ArgumentParser(prog="copyany", description="CopyAny 跨设备剪贴板历史共享")
    p.add_argument("--show", action="store_true", help="显示历史面板(实例未运行则启动并显示)")
    p.add_argument("--selftest", action="store_true", help="运行自检后退出")
    p.add_argument("--debug", action="store_true", help="调试日志到控制台")
    p.add_argument("--version", action="version", version=f"CopyAny {__version__}")
    return p.parse_args(argv)


def _setup_logging(debug: bool) -> None:
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        fh = RotatingFileHandler(config.log_path(), maxBytes=512 * 1024, backupCount=2,
                                 encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass
    if debug:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)


def _notify_running_instance() -> bool:
    """若已有实例在运行, 通知它显示面板并返回 True。"""
    from PySide6.QtNetwork import QLocalSocket
    from .app import instance_name
    sock = QLocalSocket()
    sock.connectToServer(instance_name())
    if sock.waitForConnected(400):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(400)
        sock.disconnectFromServer()
        return True
    return False


def main(argv=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.selftest:
        from .selftest import run
        return run()

    _setup_logging(args.debug)
    log = logging.getLogger(__name__)

    from PySide6.QtWidgets import QApplication
    qapp = QApplication(sys.argv[:1])   # 去掉自定义参数, 避免 Qt 误解析

    if _notify_running_instance():
        return 0                        # 已有实例: 只负责唤醒它的面板

    from .app import CopyAnyApp
    cfg, created = config.load()
    app = CopyAnyApp(qapp, first_run=created or args.show)
    if args.show:
        app.panel.show_front()
    log.info("CopyAny %s 启动 (配置: %s)", __version__, config.config_path())
    return qapp.exec()


if __name__ == "__main__":
    raise SystemExit(main())
