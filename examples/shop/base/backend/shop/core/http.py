class Request:
    def __init__(self, data: dict):
        self.data = data


class Response:
    def __init__(self, body: dict, status: int = 200):
        self.body = body
        self.status = status
