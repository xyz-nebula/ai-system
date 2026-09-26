"""Shared argparse value converters for Arena AI terminal tools."""

import argparse
import math


def positive_timeout(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Таймаут должен быть числом секунд") from error
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("Таймаут должен быть положительным")
    return seconds
