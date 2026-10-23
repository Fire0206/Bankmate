from enum import StrEnum


class CardStatus(StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"
    LOST = "lost"
    REPLACED = "replaced"


class InvalidCardTransition(ValueError):
    def __init__(self, current: CardStatus, requested: CardStatus) -> None:
        super().__init__(f"Cannot change card status from {current.value} to {requested.value}.")
        self.current = current
        self.requested = requested


def transition_card_status(current: CardStatus, requested: CardStatus) -> CardStatus:
    allowed_transitions = {
        (CardStatus.ACTIVE, CardStatus.FROZEN),
        (CardStatus.FROZEN, CardStatus.ACTIVE),
        (CardStatus.ACTIVE, CardStatus.LOST),
        (CardStatus.FROZEN, CardStatus.LOST),
        (CardStatus.LOST, CardStatus.REPLACED),
    }
    if (current, requested) not in allowed_transitions:
        raise InvalidCardTransition(current, requested)
    return requested
