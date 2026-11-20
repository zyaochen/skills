"""按 ID 查找订单。"""


def build_index(orders):
    return list(orders)


def find(index, order_id):
    for order in index:
        if order["id"] == order_id:
            return order
    return None
