"""Presentation aliases only; canonical SKU remains unchanged in API writes."""
import re


def display_sku(value):
    if isinstance(value, str) and re.fullmatch(r"DEMO-[0-9]{4}", value):
        return "ITL-" + value[5:]
    return value


def legacy_sku_query(value):
    if re.fullmatch(r"ITL-[0-9]{4}", value.strip(), re.IGNORECASE):
        return "DEMO-" + value.strip()[4:]
    return None
