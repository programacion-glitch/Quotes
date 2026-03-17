"""
Configuration Manager Module

Centralized configuration management for the RPA.
Reads settings from YAML and environment variables.
"""

import yaml
import os
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv


class ConfigManager:
    """Manages application configuration from YAML and .env files."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_path: Path to settings.yaml (auto-detects if not provided)
        """
        # Load .env file if it exists
        load_dotenv()
        
        # Determine project root
        self.project_root = Path(__file__).parent.parent
        
        # Load YAML configuration
        if config_path is None:
            resolved_path = self.project_root / "config" / "settings.yaml"
        else:
            resolved_path = Path(config_path)
        
        if not resolved_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {resolved_path}")
        
        with open(resolved_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)
        
        # Resolve environment variable placeholders
        self._resolve_env_vars(self._config)
    
    def _resolve_env_vars(self, obj: Any) -> Any:
        """
        Recursively resolve ${VAR_NAME} placeholders with environment variables.
        
        Args:
            obj: Configuration object (dict, list, str, etc.)
        """
        if isinstance(obj, dict):
            for key, value in obj.items():
                obj[key] = self._resolve_env_vars(value)
        elif isinstance(obj, list):
            return [self._resolve_env_vars(item) for item in obj]
        elif isinstance(obj, str):
            # Replace ${VAR_NAME} with environment variable
            string_val = str(obj)
            if string_val.startswith("${") and string_val.endswith("}"):
                var_name = string_val.replace("${", "").replace("}", "")
                return os.getenv(var_name, string_val)  # Keep placeholder if not found
        return obj
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.
        
        Args:
            key_path: Dot-separated path (e.g., "paths.data_input")
            default: Default value if key not found
            
        Returns:
            Configuration value
            
        Example:
            config.get("excel.checklist.sheet_name")
            config.get("matching.similarity_threshold")
        """
        keys = key_path.split('.')
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def get_path(self, key_path: str, absolute: bool = True) -> Path:
        """
        Get a path from configuration.
        
        Args:
            key_path: Dot-separated path to config value
            absolute: If True, return absolute path (relative to project root)
            
        Returns:
            Path object
        """
        path_str = self.get(key_path)
        if path_str is None:
            raise ValueError(f"Path not found in config: {key_path}")
        
        path = Path(path_str)
        
        if absolute and not path.is_absolute():
            path = self.project_root / path
        
        return path
    
    def get_all(self) -> Dict:
        """Get entire configuration dictionary."""
        return self._config.copy()
    
    # Convenience methods for common settings
    
    @property
    def data_input_dir(self) -> Path:
        """Get data input directory path."""
        return self.get_path("paths.data_input")
    
    @property
    def data_output_dir(self) -> Path:
        """Get data output directory path."""
        return self.get_path("paths.data_output")
    
    @property
    def excel_checklist_path(self) -> Path:
        """Get Excel checklist file path."""
        return self.get_path("paths.excel_checklist")
    
    @property
    def matching_threshold(self) -> float:
        """Get commodity matching threshold."""
        return float(self.get("matching.similarity_threshold", 60.0))
    
    @property
    def excel_sheet_name(self) -> str:
        """Get Excel sheet name for checklist."""
        return self.get("excel.checklist.sheet_name", "Hoja1")
    
    @property
    def excel_business_type_column(self) -> str:
        """Get Excel column for business types."""
        return self.get("excel.checklist.column_business_type", "A")
    
    @property
    def excel_comments_column(self) -> str:
        """Get Excel column for comments."""
        return self.get("excel.checklist.column_comments", "B")
    
    @property
    def openai_base_url(self) -> str:
        """Get OpenAI Base URL (Local Proxy)."""
        return os.getenv("OPENAI_BASE_URL", "http://localhost:3000/v1")
        
    @property
    def openai_api_key(self) -> str:
        """Get OpenAI API Key (Local Proxy)."""
        return os.getenv("OPENAI_API_KEY", "sk-local-proxy")
        
    def __repr__(self) -> str:
        return f"<ConfigManager: {len(self._config)} sections loaded>"


# Global configuration instance
_config_instance: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    """
    Get global configuration instance (singleton pattern).
    
    Returns:
        ConfigManager instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigManager()
    return _config_instance


def reload_config(config_path: Optional[str] = None):
    """
    Reload configuration from file.
    
    Args:
        config_path: Optional path to config file
    """
    global _config_instance
    _config_instance = ConfigManager(config_path)
