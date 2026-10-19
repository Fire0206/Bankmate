class BankingRuleError(RuntimeError):
    """A deterministic business rule prevented a simulated operation."""

    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
