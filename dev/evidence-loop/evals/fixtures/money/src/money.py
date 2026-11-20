"""金额工具：以"厘"（千分之一元）为单位的整数金额换算成"分"。"""


def round_cents(mills):
    """四舍五入到分，半分远离零进位：1125 厘 -> 113 分，-1125 厘 -> -113 分。"""
    return (mills + 5) // 10


def format_cents(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"
