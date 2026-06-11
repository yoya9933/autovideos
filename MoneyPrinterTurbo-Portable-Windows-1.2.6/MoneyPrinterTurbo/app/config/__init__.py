import os
import sys
from pathlib import Path

from loguru import logger

from app.config import config
from app.utils import utils


def __init_logger():
    # _log_file = utils.storage_dir("logs/server.log")
    _lvl = config.log_level
    root_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    )

    def format_record(record):
        # 获取日志记录中的文件全路径
        file_path = record["file"].path
        # 将绝对路径转换为相对于项目根目录的路径
        relative_path = os.path.relpath(file_path, root_dir)
        # 更新记录中的文件路径
        record["file"].path = f"./{relative_path}"
        # 返回修改后的格式字符串
        # 您可以根据需要调整这里的格式
        _format = (
            "<green>{time:%Y-%m-%d %H:%M:%S}</> | "
            + "<level>{level}</> | "
            + '"{file.path}:{line}":<blue> {function}</> '
            + "- <level>{message}</>"
            + "\n"
        )
        return _format

    logger.remove()

    # Windows 終端預設使用 cp950/cp936，無法顯示部分簡體中文字元。
    # 這裡強制用 UTF-8 包裝 stdout，避免 loguru 寫入時拋出
    # UnicodeEncodeError 導致日誌遺失。
    _log_sink = sys.stdout
    if hasattr(sys.stdout, "buffer"):
        import io
        _log_sink = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )

    logger.add(
        _log_sink,
        level=_lvl,
        format=format_record,
        colorize=True,
    )

    # 檔案 sink：每天午夜 rotation，保留 30 天。
    # log 目錄：storage/auto_publish/logs/，檔名依日期命名，方便事後查閱。
    _log_dir = Path(config.root_dir) / "storage" / "auto_publish" / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = _log_dir / "daily_{time:YYYY-MM-DD}.log"
    logger.add(
        str(_log_file),
        level=_lvl,
        format=format_record,
        rotation="00:00",      # 每天午夜建立新檔
        retention="30 days",   # 30 天後自動刪除舊 log
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
        enqueue=True,          # 非同步寫入，避免阻塞主流程
        colorize=False,        # 檔案不需要 ANSI color code
    )


__init_logger()
