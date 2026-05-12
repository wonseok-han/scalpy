class ScalpyError(Exception):
    """Base exception for all Scalpy errors."""


class BrokerError(ScalpyError):
    """Broker communication error."""


class AuthenticationError(BrokerError):
    """API authentication failure."""


class OrderError(BrokerError):
    """Order execution failure."""


class InsufficientBalanceError(OrderError):
    """Insufficient balance to place order."""


class StrategyError(ScalpyError):
    """Strategy execution error."""


class DataError(ScalpyError):
    """Data layer error."""


class ConnectionError(DataError):  # noqa: A001
    """Network connection failure."""
