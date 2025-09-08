import os
from typing import List, Dict
from pydantic import BaseModel, Field, field_validator, ConfigDict
import yaml

class AutoMessageRemoval(BaseModel):
    """Class for holding an auto message removal config instance"""
    channel_id: int # The channel to monitor for posted messages.
    regex_matching: str = None # If message does not match this RegEx, it is NOT removed.
    regex_not_matching: str = None # If message matches this RegEx, it is NOT removed.
    removal_delay_seconds: float = None # How long to wait before removing the message.
    response_message: str = None # Response message to remove messages.

class ModLog(BaseModel):
    """Class for holding the configuration for the moderation log feature"""
    log_channel_id: int # The channel to post in for any observed moderator actions.
    ignored_channels: List[int] = [] # List of Channel IDs to ignore moderator actions in.

class Server(BaseModel):
    """Class for holding a server's configuration"""
    id: int # The ID of the server (guild).
    name: str # Name of the server. Only used for console logging.
    report_channel_id: int # The channel to post user reports to.
    report_role_ping_id: int = None # The role ID to ping for any user reports.
    log_channel_id: int = None # Channe ID to post in for any observed moderator actions.
    ignored_channels: List[int] = [] # List of Channel IDs to ignore moderator actions in.
#    mod_logs: Optional[Config_ModLog] = None # Configuration for the moderation log feature.
#    reporting: Optional[Config_Reports] = None # configuration for the user reports feature.
    auto_message_removals: List[AutoMessageRemoval] = [] # Multiple configurations for the auto message removal feature.

class Bot(BaseModel):
    """Class for holding the bot's parameters"""
    model_config = ConfigDict(validate_default=True)

    token: str = Field(default_factory=lambda: os.getenv('BOT_TOKEN', ""), min_length=72, max_length=72) # The token for the bot. If not specified in YAML, will default to 'BOT_TOKEN' from the environment.

class Config(BaseModel):
    """Class for holding the bot's entire configuration YAML"""
    db_size_warning_threshold: int = 100
    bot: Bot = Field(default_factory=lambda: Bot()) # General bot configuration settings.
    servers: Dict[int, Server] # Dictionary of servers to operate on. Key is the server ID.

    @field_validator('servers', mode='before')
    def validate_servers(cls, v):
        if not isinstance(v, dict):
            raise ValueError("servers must be a dictionary with server IDs as keys")
        for key, value in v.items():
            v[key]["id"] = key
        return v

    @staticmethod
    def load(file: str): # -> Self # Python 3.10 does not support Self from typing library
        """Loads the bot YAML configuration from the given file path.
        
        @param file The path to the file to load."""
        with open(file, mode='r') as f:
            config_yaml = yaml.safe_load(f)

        output = Config(**config_yaml)

        return output

if __name__ == "__main__":
    # Test config loader
    config = Config.load("config.yml")
    print(config.__dict__)
