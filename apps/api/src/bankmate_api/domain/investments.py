UNITS_SCALE = 1_000_000


class InvalidInvestmentError(ValueError):
    pass


def product_is_suitable(*, user_risk_level: int, product_risk_level: int) -> bool:
    return 1 <= product_risk_level <= user_risk_level <= 5


def units_for_amount(*, amount_minor: int, unit_price_minor: int) -> int:
    if amount_minor <= 0 or unit_price_minor <= 0:
        raise InvalidInvestmentError("申购金额和产品价格必须大于零。")
    units = amount_minor * UNITS_SCALE // unit_price_minor
    if units <= 0:
        raise InvalidInvestmentError("金额不足以购买最小模拟份额。")
    return units


def value_for_units(*, units_micros: int, unit_price_minor: int) -> int:
    if units_micros < 0 or unit_price_minor <= 0:
        raise InvalidInvestmentError("持仓份额或产品价格无效。")
    return units_micros * unit_price_minor // UNITS_SCALE
