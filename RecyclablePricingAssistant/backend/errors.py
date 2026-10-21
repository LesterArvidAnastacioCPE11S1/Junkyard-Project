# errors.py - one error type the services raise and the API turns into an HTTP response.
class ApiError(Exception):
    def __init__(self, status_code: int, detail: str, headers: dict = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers
