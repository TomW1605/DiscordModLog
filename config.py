import os
from typing import Optional, List, Dict
from pydantic import BaseModel, Field, field_validator
import yaml

class AutoMessageRemoval(BaseModel):
    """Class for holding an auto message removal config instance"""
    channel_id: int # The channel to monitor for posted messages.
    regex_matching: Optional[str] = None # If message does not match this RegEx, it is NOT removed.
    regex_not_matching: Optional[str] = None # If message matches this RegEx, it is NOT removed.
    removal_delay_seconds: Optional[float] = None # How long to wait before removing the message.
    response_message: Optional[str] = None # Response message to remove messages.

class Server(BaseModel):
    """Class for holding a server's configuration"""
    id: int # The ID of the server (guild).
    name: str # Name of the server. Only used for console logging.
    report_channel_id: int # The channel to post user reports to.
    report_role_ping_id: Optional[int] = None # The role ID to ping for any user reports.
    log_channel_id: Optional[int] # Channe ID to post in for any observed moderator actions.
    ignored_channels: Optional[List[int]] = None # List of Channel IDs to ignore moderator actions in.
#    mod_logs: Optional[Config_ModLog] = None # Configuration for the moderation log feature.
#    reporting: Optional[Config_Reports] = None # configuration for the user reports feature.
    auto_message_removals: Optional[List[AutoMessageRemoval]] = None # Multiple configurations for the auto message removal feature.

class Bot(BaseModel):
    """Class for holding the bot's parameters"""
    token: Optional[str] = Field(default_factory=lambda: os.getenv('BOT_TOKEN', None)) # The token for the bot. If not specified in YAML, will default to 'BOT_TOKEN' from the environment.

class Config(BaseModel):
    """Class for holding the bot's entire configuration YAML"""
    db_size_warning_threshold: int = 100
    bot: Optional[Bot] = Field(default_factory=lambda: Bot()) # General bot configuration settings.
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
            config = yaml.safe_load(f)

        output = Config(**config)

        # Make sure bot entry actually exists, despite being "Optional"
        if not output.bot:
            output.bot = Bot()

        # Override bot token with environment variable, if set
        output.bot.token = os.getenv('BOT_TOKEN', output.bot.token)
        
        # Validate bot token is set
        if output.bot.token is None:
            raise ValueError("BOT_TOKEN is not set in environment variables, and bot->token not found in config.yml.")

        return output

if __name__ == "__main__":
    # Test config loader
    config = Config.load("config.yml")
    print(config.__dict__)
