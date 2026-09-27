# TextNow Home Assistant Integration

A powerful Home Assistant integration for TextNow SMS that enables multi-step conversational automations through generic conversation primitives.

## Features

- 📱 Full SMS support (send/receive)
- 🔔 Works with Home Assistant's notify service: `notify.textnow`, plus a notify entity per contact
- 🔄 Automatic message polling with deduplication
- 👥 UI-managed contact list
- 🎯 Smart prompts with reply parsing
- 📊 Per-contact sensor entities
- 🔐 Phone number allowlist security
- 💾 Persistent storage for contacts, pending, and context
- ⚡ Event-driven architecture

## Installation

Available via HACS or manual installation. See README.md for details.

## Brand-new TextNow account?

TextNow enables a new account for its phone apps immediately and for the web a
day or two later, without telling you. Signing in at textnow.com fails for
roughly the first 24 hours, and sending is refused as "not yet set up for web
access" until around 48 hours, in the TextNow web app and here alike. Nothing
to fix — see [If you just signed up for TextNow](https://github.com/KennebecRiver66/Home-Assistant-TextNow#if-you-just-signed-up-for-textnow).

