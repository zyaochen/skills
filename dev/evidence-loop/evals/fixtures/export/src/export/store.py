"""订单仓储（只读）。"""

ORDERS = [{"id": i, "amount": i * 100} for i in range(1, 26)]


def page(offset, limit):
    return ORDERS[offset:offset + limit]
