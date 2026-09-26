"""Constants for the TextNow integration."""
from datetime import timedelta
from typing import Final

DOMAIN: Final = "textnow"

# Device name; entity IDs are derived from it, so keep it short
DEVICE_NAME: Final = "TextNow"

# Event types
EVENT_MESSAGE_RECEIVED: Final = "textnow_message_received"
EVENT_REPLY_PARSED: Final = "textnow_reply_parsed"

# Storage keys
STORAGE_KEY: Final = f"{DOMAIN}.storage"
STORAGE_VERSION: Final = 1

# Config entry data keys
CONF_USERNAME: Final = "username"
CONF_COOKIES: Final = "cookies"
CONF_POLLING_INTERVAL: Final = "polling_interval"
CONF_ENTITY_IDS_MIGRATED: Final = "entity_ids_migrated"

# Where the cookie instructions live, used by the repair item and the forms
COOKIE_HELP_URL: Final = (
    "https://github.com/KennebecRiver66/Home-Assistant-TextNow"
    "#getting-your-cookies"
)

# Defaults
DEFAULT_POLLING_INTERVAL: Final = 30  # seconds
MIN_POLLING_INTERVAL: Final = 15  # seconds
MAX_POLLING_INTERVAL: Final = 600  # seconds
DEFAULT_TTL_SECONDS: Final = 300  # 5 minutes

# Upper bound for the backoff applied after repeated polling failures
MAX_BACKOFF_INTERVAL: Final = timedelta(minutes=15)

# Attributes
ATTR_PHONE: Final = "phone"
ATTR_LAST_INBOUND: Final = "last_inbound"
ATTR_LAST_INBOUND_TS: Final = "last_inbound_ts"
ATTR_LAST_OUTBOUND: Final = "last_outbound"
ATTR_LAST_OUTBOUND_TS: Final = "last_outbound_ts"
ATTR_PENDING: Final = "pending"
ATTR_CONTEXT: Final = "context"
ATTR_CONTACT_ID: Final = "contact_id"
ATTR_MESSAGE_ID: Final = "message_id"
ATTR_TIMESTAMP: Final = "timestamp"
ATTR_TEXT: Final = "text"
ATTR_KEY: Final = "key"
ATTR_TYPE: Final = "type"
ATTR_VALUE: Final = "value"
ATTR_RAW_TEXT: Final = "raw_text"
ATTR_OPTION_INDEX: Final = "option_index"

# Menu defaults
DEFAULT_MENU_TIMEOUT: Final = 30  # 30 seconds
DEFAULT_NUMBER_FORMAT: Final = "{n}. {option}"
DEFAULT_MENU_HEADER: Final = "Please select an option:"
DEFAULT_MENU_FOOTER: Final = "Reply with the number of your choice"
