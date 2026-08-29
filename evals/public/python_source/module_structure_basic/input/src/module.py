"""Synthetic module structure example.

Only the first bounded summary is relevant.
"""

import os
from package.tools import helper


def transform(value: int, option="DEFAULT_LITERAL_SENTINEL") -> str:
    body_value = "BODY_LITERAL_SENTINEL"
    return body_value


async def fetch(item, *, timeout: float = 2.0):
    return item
