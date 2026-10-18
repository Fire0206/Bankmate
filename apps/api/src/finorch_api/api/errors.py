from fastapi import HTTPException


class ContractHTTPException(HTTPException):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.error_code = code
        self.public_message = message
