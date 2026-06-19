"""
Configuration management for the GCC Research Intelligence Platform.

This module handles environment variables, application settings, and 
configuration validation for the platform.
"""

import os
from typing import Optional, Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class DatabaseConfig:
    """Database configuration settings."""
    supabase_url: str
    supabase_key: str
    pool_size: int = 5
    pool_recycle: int = 3600
    echo_sql: bool = False


@dataclass
class OpenAIConfig:
    """OpenAI API configuration settings."""
    api_key: str
    model: str = "gpt-4o"
    max_tokens: int = 2000
    temperature: float = 0.1
    max_retries: int = 3
    retry_delay: float = 1.0
    max_retry_delay: float = 60.0


@dataclass
class AppConfig:
    """General application configuration settings."""
    log_level: str = "INFO"
    max_upload_size_mb: int = 50
    cache_expiry_days: int = 30
    session_timeout_hours: int = 24
    max_concurrent_requests: int = 10
    debug_mode: bool = False


class ConfigManager:
    """Configuration manager for the GCC Research Intelligence Platform."""
    
    def __init__(self):
        """Initialize configuration from environment variables."""
        self._database_config: Optional[DatabaseConfig] = None
        self._openai_config: Optional[OpenAIConfig] = None
        self._app_config: Optional[AppConfig] = None
        
        # Validate configuration on initialization
        self.validate_configuration()
    
    @property
    def database(self) -> DatabaseConfig:
        """Get database configuration."""
        if self._database_config is None:
            self._database_config = DatabaseConfig(
                supabase_url=self._get_required_env("SUPABASE_URL"),
                supabase_key=self._get_required_env("SUPABASE_KEY"),
                pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
                pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "3600")),
                echo_sql=os.getenv("DB_ECHO_SQL", "false").lower() == "true"
            )
        return self._database_config
    
    @property
    def openai(self) -> OpenAIConfig:
        """
        Get OpenAI configuration.

        api_key here is read directly from the env var only -- it is NOT
        the authoritative source of the key actually used for research
        calls. That's resolved per-call via src.utils.api_keys.get_api_key,
        which checks the Settings UI's DB-stored value first and falls back
        to this same env var. Deliberately optional (not _get_required_env)
        so that simply reading retry/model tuning knobs off this object --
        which both ResearchEngine and GeminiEngine do, the latter even when
        no OpenAI key is configured at all -- never raises just because
        OPENAI_API_KEY isn't set.
        """
        if self._openai_config is None:
            self._openai_config = OpenAIConfig(
                api_key=os.getenv("OPENAI_API_KEY", ""),
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                max_tokens=int(os.getenv("OPENAI_MAX_TOKENS", "2000")),
                temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.1")),
                max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "3")),
                retry_delay=float(os.getenv("OPENAI_RETRY_DELAY", "1.0")),
                max_retry_delay=float(os.getenv("OPENAI_MAX_RETRY_DELAY", "60.0"))
            )
        return self._openai_config
    
    @property
    def app(self) -> AppConfig:
        """Get application configuration."""
        if self._app_config is None:
            self._app_config = AppConfig(
                log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
                max_upload_size_mb=int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")),
                cache_expiry_days=int(os.getenv("CACHE_EXPIRY_DAYS", "30")),
                session_timeout_hours=int(os.getenv("SESSION_TIMEOUT_HOURS", "24")),
                max_concurrent_requests=int(os.getenv("MAX_CONCURRENT_REQUESTS", "10")),
                debug_mode=os.getenv("DEBUG_MODE", "false").lower() == "true"
            )
        return self._app_config
    
    def _get_required_env(self, key: str) -> str:
        """
        Get required environment variable.
        
        Args:
            key: Environment variable key.
            
        Returns:
            Environment variable value.
            
        Raises:
            ValueError: If required environment variable is not set.
        """
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Required environment variable {key} is not set")
        return value
    
    def validate_configuration(self) -> Dict[str, Any]:
        """
        Validate all configuration settings.
        
        Returns:
            Dictionary with validation results.
        """
        validation_results = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        try:
            # Validate required environment variables
            required_vars = ["SUPABASE_URL", "SUPABASE_KEY", "OPENAI_API_KEY"]
            for var in required_vars:
                if not os.getenv(var):
                    validation_results["errors"].append(f"Missing required environment variable: {var}")
                    validation_results["valid"] = False
            
            # Validate numeric configurations
            try:
                max_upload_size = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
                if max_upload_size <= 0 or max_upload_size > 500:
                    validation_results["warnings"].append(
                        f"MAX_UPLOAD_SIZE_MB ({max_upload_size}) should be between 1 and 500"
                    )
            except ValueError:
                validation_results["errors"].append("MAX_UPLOAD_SIZE_MB must be a valid integer")
                validation_results["valid"] = False
            
            try:
                cache_expiry = int(os.getenv("CACHE_EXPIRY_DAYS", "30"))
                if cache_expiry <= 0 or cache_expiry > 365:
                    validation_results["warnings"].append(
                        f"CACHE_EXPIRY_DAYS ({cache_expiry}) should be between 1 and 365"
                    )
            except ValueError:
                validation_results["errors"].append("CACHE_EXPIRY_DAYS must be a valid integer")
                validation_results["valid"] = False
            
            # Validate OpenAI configuration
            try:
                temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.1"))
                if temperature < 0 or temperature > 2:
                    validation_results["warnings"].append(
                        f"OPENAI_TEMPERATURE ({temperature}) should be between 0 and 2"
                    )
            except ValueError:
                validation_results["errors"].append("OPENAI_TEMPERATURE must be a valid float")
                validation_results["valid"] = False
            
            # Validate log level
            valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            log_level = os.getenv("LOG_LEVEL", "INFO").upper()
            if log_level not in valid_log_levels:
                validation_results["warnings"].append(
                    f"LOG_LEVEL ({log_level}) should be one of: {', '.join(valid_log_levels)}"
                )
        
        except Exception as e:
            validation_results["errors"].append(f"Configuration validation error: {str(e)}")
            validation_results["valid"] = False
        
        return validation_results
    
    def get_config_summary(self) -> Dict[str, Any]:
        """
        Get a summary of current configuration (without sensitive data).
        
        Returns:
            Dictionary with configuration summary.
        """
        return {
            "database": {
                "has_supabase_url": bool(os.getenv("SUPABASE_URL")),
                "has_supabase_key": bool(os.getenv("SUPABASE_KEY")),
                "pool_size": self.database.pool_size,
                "pool_recycle": self.database.pool_recycle,
                "echo_sql": self.database.echo_sql
            },
            "openai": {
                "has_api_key": bool(os.getenv("OPENAI_API_KEY")),
                "model": self.openai.model,
                "max_tokens": self.openai.max_tokens,
                "temperature": self.openai.temperature,
                "max_retries": self.openai.max_retries
            },
            "app": {
                "log_level": self.app.log_level,
                "max_upload_size_mb": self.app.max_upload_size_mb,
                "cache_expiry_days": self.app.cache_expiry_days,
                "session_timeout_hours": self.app.session_timeout_hours,
                "debug_mode": self.app.debug_mode
            }
        }


# Global configuration instance
config = ConfigManager()


def get_config() -> ConfigManager:
    """
    Get the global configuration manager instance.
    
    Returns:
        ConfigManager instance.
    """
    return config


def validate_environment() -> bool:
    """
    Validate the current environment configuration.
    
    Returns:
        True if configuration is valid, False otherwise.
    """
    validation_results = config.validate_configuration()
    return validation_results["valid"]


if __name__ == "__main__":
    # Script can be run directly to validate configuration
    print("GCC Research Intelligence Platform - Configuration Validation")
    print("=" * 60)
    
    validation_results = config.validate_configuration()
    
    if validation_results["valid"]:
        print("✅ Configuration is valid!")
    else:
        print("❌ Configuration validation failed!")
    
    if validation_results["errors"]:
        print("\nErrors:")
        for error in validation_results["errors"]:
            print(f"  ❌ {error}")
    
    if validation_results["warnings"]:
        print("\nWarnings:")
        for warning in validation_results["warnings"]:
            print(f"  ⚠️  {warning}")
    
    print("\nConfiguration Summary:")
    summary = config.get_config_summary()
    for section, settings in summary.items():
        print(f"\n{section.upper()}:")
        for key, value in settings.items():
            print(f"  {key}: {value}")