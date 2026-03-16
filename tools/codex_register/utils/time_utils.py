from datetime import datetime


def get_now() -> datetime:
    """获取当前时间 (naive datetime)。"""
    return datetime.now()
