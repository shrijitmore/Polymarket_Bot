"""
Configuration management for Polymarket arbitrage bot.
Uses Pydantic for validation and type safety.
"""
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # ========================================
    # POLYMARKET CONFIGURATION
    # ========================================
    polymarket_private_key: Optional[str] = Field(default=None, description="Polymarket private key for signing orders")
    polymarket_api_key: Optional[str] = Field(default=None, description="Polymarket API key (optional)")
    polymarket_api_secret: Optional[str] = Field(default=None, description="Polymarket API secret (optional)")
    polymarket_api_passphrase: Optional[str] = Field(default=None, description="Polymarket API passphrase (optional)")
    polymarket_chain_id: int = Field(default=137, description="Polygon chain ID")
    polymarket_api_url: str = Field(default="https://clob.polymarket.com", description="CLOB API URL")
    
    # ========================================
    # MONGODB CONFIGURATION
    # ========================================
    mongo_uri: str = Field(default="mongodb://localhost:27017", description="MongoDB connection URI")
    mongo_db_name: str = Field(default="polymarket_bot", description="MongoDB database name")
    
    # ========================================
    # BINANCE CONFIGURATION
    # ========================================
    binance_ws_url: str = Field(
        default="wss://stream.binance.com:9443/ws",
        description="Binance WebSocket URL"
    )
    
    # ========================================
    # TELEGRAM ALERTS
    # ========================================
    telegram_bot_token: Optional[str] = Field(default=None, description="Telegram bot token")
    telegram_chat_id: Optional[str] = Field(default=None, description="Telegram chat ID")
    
    # ========================================
    # TRADING PARAMETERS
    # ========================================
    bankroll: float = Field(default=5000.0, gt=0, description="Total bankroll in USD")
    max_arb_position_pct: float = Field(default=2.0, gt=0, le=10, description="Max arb position %")
    max_late_position_pct: float = Field(default=1.5, gt=0, le=10, description="Max late position %")
    max_daily_exposure_pct: float = Field(default=25.0, gt=0, le=100, description="Max daily exposure %")
    max_concurrent_positions: int = Field(default=10, gt=0, description="Max concurrent positions")
    daily_loss_halt_pct: float = Field(default=5.0, gt=0, description="Daily loss halt %")
    max_consecutive_fails: int = Field(default=3, gt=0, description="Max consecutive failed arbs")
    
    # ========================================
    # STRATEGY PARAMETERS
    # ========================================
    min_arb_edge_pct: float = Field(default=2.0, gt=0, description="Minimum arbitrage edge %")
    max_slippage_pct: float = Field(default=0.3, gt=0, description="Maximum slippage %")
    order_timeout_seconds: int = Field(default=5, gt=0, description="Order timeout in seconds")
    min_market_volume: float = Field(default=5000.0, gt=0, description="Minimum market volume USD")
    min_time_to_close_minutes: int = Field(default=30, gt=0, description="Min time to close in minutes")
    max_spread_one_of_many: float = Field(default=2.0, gt=0, description="Max spread for 1-of-N arb %")
    max_spread_yes_no: float = Field(default=1.5, gt=0, description="Max spread for YES/NO arb %")
    max_spread_late_market: float = Field(default=1.0, gt=0, description="Max spread for late market %")
    
    # ========================================
    # LATE-MARKET STRATEGY (BTC 5m)
    # ========================================
    enable_late_market: bool = Field(default=True, description="Enable late-market strategy")
    late_market_window_start: int = Field(default=180, gt=0, description="Late window start (sec before close)")
    late_market_window_end: int = Field(default=60, gt=0, description="Late window end (sec before close)")
    late_market_min_deviation_pct: float = Field(default=0.05, gt=0, description="Min BTC price deviation %")
    late_market_max_volatility_pct: float = Field(default=1.5, gt=0, description="Max volatility %")
    late_market_max_price: float = Field(default=0.95, gt=0, le=1, description="Max entry price")

    # ========================================
    # BTC 5M SCAN SETTINGS
    # ========================================
    btc_5m_scan_interval_seconds: int = Field(default=2, gt=0, description="BTC 5m scan interval seconds")
    btc_5m_min_volume: float = Field(default=100.0, gt=0, description="Min volume for BTC 5m markets")
    
    # ========================================
    # FEATURE FLAGS
    # ========================================
    dry_run: bool = Field(default=True, description="Enable DRY RUN mode")
    enable_one_of_many: bool = Field(default=True, description="Enable 1-of-N arbitrage")
    enable_yes_no: bool = Field(default=True, description="Enable YES/NO arbitrage")
    scanner_interval_seconds: int = Field(default=5, gt=0, description="Scanner interval seconds")
    
    # ========================================
    # LOGGING
    # ========================================
    log_level: str = Field(default="INFO", description="Logging level")
    
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v = v.upper()
        if v not in valid_levels:
            raise ValueError(f"Invalid log level. Must be one of: {valid_levels}")
        return v
    
    @field_validator("late_market_window_start", "late_market_window_end")
    @classmethod
    def validate_late_window(cls, v: int) -> int:
        """Validate late market window."""
        if v < 10 or v > 600:
            raise ValueError("Late market window must be between 10 and 600 seconds")
        return v
    
    def model_post_init(self, __context) -> None:
        """Validate authentication credentials after model initialization."""
        if not self.dry_run:
            # For live trading, need either private key or API credentials
            has_private_key = bool(self.polymarket_private_key)
            has_api_creds = all([
                self.polymarket_api_key,
                self.polymarket_api_secret,
                self.polymarket_api_passphrase
            ])
            
            if not has_private_key and not has_api_creds:
                raise ValueError(
                    "Live trading requires either POLYMARKET_PRIVATE_KEY or "
                    "all of (POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_API_PASSPHRASE)"
                )
    
    # ========================================
    # COMPUTED PROPERTIES
    # ========================================
    @property
    def max_arb_position_size(self) -> float:
        """Maximum position size for arbitrage in USD."""
        return self.bankroll * (self.max_arb_position_pct / 100.0)
    
    @property
    def max_late_position_size(self) -> float:
        """Maximum position size for late market in USD."""
        return self.bankroll * (self.max_late_position_pct / 100.0)
    
    @property
    def max_daily_exposure(self) -> float:
        """Maximum total daily exposure in USD."""
        return self.bankroll * (self.max_daily_exposure_pct / 100.0)
    
    @property
    def daily_loss_halt_amount(self) -> float:
        """Daily loss amount that triggers halt in USD."""
        return self.bankroll * (self.daily_loss_halt_pct / 100.0)
    
    @property
    def telegram_enabled(self) -> bool:
        """Check if Telegram alerts are enabled."""
        return bool(self.telegram_bot_token and self.telegram_chat_id)


# Global settings instance
settings = Settings()


def reload_settings() -> Settings:
    """Reload settings from environment (useful for testing)."""
    global settings
    settings = Settings()
    return settings
