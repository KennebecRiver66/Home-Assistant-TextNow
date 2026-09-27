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
CONF_KEEPALIVE_PHONE: Final = "keepalive_phone"
CONF_KEEPALIVE_DAYS: Final = "keepalive_days"
CONF_KEEPALIVE_MESSAGE: Final = "keepalive_message"

# Where the cookie instructions live, used by the repair item and the forms
COOKIE_HELP_URL: Final = (
    "https://github.com/KennebecRiver66/Home-Assistant-TextNow"
    "#getting-your-cookies"
)

# TextNow enables a new account for the web days after it works on a phone,
# which looks exactly like a broken integration unless someone says otherwise.
NEW_ACCOUNT_HELP_URL: Final = (
    "https://github.com/KennebecRiver66/Home-Assistant-TextNow"
    "#if-you-just-signed-up-for-textnow"
)

# Defaults
DEFAULT_POLLING_INTERVAL: Final = 30  # seconds
MIN_POLLING_INTERVAL: Final = 15  # seconds
MAX_POLLING_INTERVAL: Final = 600  # seconds
DEFAULT_TTL_SECONDS: Final = 300  # 5 minutes

# Upper bound for the backoff applied after repeated polling failures
MAX_BACKOFF_INTERVAL: Final = timedelta(minutes=15)

# How often to retry once TextNow has rejected the session. Polling has to
# slow right down -- retrying a dead session every 30 seconds is what turns
# one failure into thousands of requests a day -- but it must not stop. The
# poll is the only thing that can notice the session working again, and the
# only thing that can put the reauth prompt back after it is dismissed.
AUTH_RECOVERY_INTERVAL: Final = timedelta(minutes=30)

# TextNow gives an unused number back to the pool. The exact idle time is not
# published and has changed over the years, so the default leaves room under a
# week rather than sitting on the edge of it.
DEFAULT_KEEPALIVE_DAYS: Final = 5
MIN_KEEPALIVE_DAYS: Final = 1
MAX_KEEPALIVE_DAYS: Final = 30
DEFAULT_KEEPALIVE_MESSAGE: Final = (
    "Keeping this TextNow number in use. Sent by Home Assistant, no reply needed."
)
# How long to wait before trying a keep-alive again after one did not go out.
KEEPALIVE_RETRY_INTERVAL: Final = timedelta(hours=1)

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
