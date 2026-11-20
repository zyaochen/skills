"""租约服务与带令牌围栏的存储。"""


class LeaseService:
    def __init__(self):
        self.token = 0
        self.owner = None

    def acquire(self, worker):
        if self.owner is not None:
            return None
        self.token += 1
        self.owner = worker
        return self.token

    def expire(self):
        self.owner = None


class Store:
    def __init__(self):
        self.value = None
        self.token = 0

    def write(self, token, value):
        """按令牌比较并写入；成功返回 True。"""
        self.value = value
        self.token = token
        return True
