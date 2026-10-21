class DoudianError(Exception):
    def __init__(self, code, message, *, waiting=False):
        super().__init__(message)
        self.code = code
        self.waiting = waiting


class WaitingHuman(DoudianError):
    def __init__(self, code, message):
        super().__init__(code, message, waiting=True)
