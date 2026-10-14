class AdoptError(Exception):
    def __init__(self, *messages: str) -> None:
        super().__init__("\n".join(messages))
        self.messages = messages
