from decimal import Decimal, InvalidOperation


class InvalidTransferError(ValueError):
    pass


def parse_money_to_minor(value: str) -> int:
    try:
        amount = Decimal(value.strip())
    except InvalidOperation as exc:
        raise InvalidTransferError("金额格式无效。") from exc
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise InvalidTransferError("金额必须大于零且最多保留两位小数。")
    minor = amount * 100
    if minor != minor.to_integral_value():
        raise InvalidTransferError("金额最多保留两位小数。")
    return int(minor)


def split_amount(total_minor: int, participant_count: int) -> tuple[int, ...]:
    if total_minor <= 0 or participant_count < 2 or participant_count > 11:
        raise InvalidTransferError("分账金额或参与人数无效。")
    share, remainder = divmod(total_minor, participant_count)
    if share <= 0:
        raise InvalidTransferError("总金额不足以按参与人数分账。")
    return tuple(share + (1 if index < remainder else 0) for index in range(participant_count))
