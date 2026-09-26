/**
 * TextNow panel for Home Assistant.
 *
 * One screen for the three things people actually do: see whether the
 * connection is healthy, manage contacts, and send a message to check it
 * works. Everything is written for someone who has never opened a browser
 * developer console.
 */

const DOCS_FALLBACK =
  "https://github.com/KennebecRiver66/Home-Assistant-TextNow#getting-your-cookies";

const INTEGRATION_PAGE = "/config/integrations/integration/textnow";
const ADD_ACCOUNT_PAGE = "/config/integrations/dashboard/add?domain=textnow";

/** Found next to this module, so the preview harness resolves it too. */
const LOGO_URL = new URL("./textnow-logo.png", import.meta.url).href;
const HELP_FIND_URL = new URL("./help-find-messaging.png", import.meta.url).href;
const HELP_COPY_URL = new URL("./help-copy-as-curl.png", import.meta.url).href;

/** How often the panel asks Home Assistant how the accounts are doing. */
const POLL_MS = 15000;

const MESSAGE_LIMIT = 300;

const ICON = {
  menu: "M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z",
  plus: "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z",
  refresh:
    "M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z",
  check:
    "M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M11,16.5L6.5,12L7.91,10.59L11,13.67L16.59,8.09L18,9.5L11,16.5Z",
  alert:
    "M13,13H11V7H13M13,17H11V15H13M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2Z",
  warning: "M13,14H11V9H13M13,18H11V16H13M1,21H23L12,2L1,21Z",
  pause:
    "M15,16H13V8H15M11,16H9V8H11M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2Z",
  send: "M2,21L23,12L2,3V10L17,12L2,14V21Z",
  pencil:
    "M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z",
  trash:
    "M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z",
  close:
    "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  cog: "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.96 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.94C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z",
  help: "M11,18H13V16H11V18M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4A8,8 0 0,1 20,12A8,8 0 0,1 12,20M12,6A4,4 0 0,0 8,10H10A2,2 0 0,1 12,8A2,2 0 0,1 14,10C14,11.33 12,11.75 12,14H14C14,12.25 16,12 16,10A4,4 0 0,0 12,6Z",
  external:
    "M14,3V5H17.59L7.76,14.83L9.17,16.24L19,6.41V10H21V3M19,19H5V5H12V3H5C3.89,3 3,3.9 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V12H19V19Z",
  message:
    "M12,3C17.5,3 22,6.58 22,11C22,15.42 17.5,19 12,19C10.76,19 9.57,18.82 8.47,18.5C5.55,21 2,21 2,21C4.33,18.67 4.7,17.1 4.75,16.5C3.05,15.07 2,13.13 2,11C2,6.58 6.5,3 12,3Z",
  people:
    "M12,4A4,4 0 0,1 16,8A4,4 0 0,1 12,12A4,4 0 0,1 8,8A4,4 0 0,1 12,4M12,14C16.42,14 20,15.79 20,18V20H4V18C4,15.79 7.58,14 12,14Z",
  shield:
    "M12,1L3,5V11C3,16.55 6.84,21.74 12,23C17.16,21.74 21,16.55 21,11V5L12,1M10.94,15.54L7.4,12L8.81,10.59L10.94,12.71L15.19,8.46L16.6,9.88L10.94,15.54Z",
};

/** Plain-language copy for each connection state. */
const STATUS_COPY = {
  connected: {
    tone: "ok",
    icon: ICON.check,
    label: "Connected",
    headline: "Everything is working",
  },
  reauth_required: {
    tone: "bad",
    icon: ICON.alert,
    label: "Sign-in needed",
    headline: "TextNow needs a new sign-in",
    detail:
      "TextNow signed this session out, so messages cannot be sent or received. " +
      "Pasting a fresh cookie line fixes it. Your contacts and automations are kept.",
    action: { label: "Fix this now", act: "fix" },
  },
  offline: {
    tone: "warn",
    icon: ICON.warning,
    label: "Offline",
    headline: "Cannot reach TextNow right now",
    detail:
      "This is usually a short network problem. Home Assistant keeps retrying on " +
      "its own, waiting a little longer after each failure.",
    action: { label: "Try again", act: "check" },
  },
  disabled: {
    tone: "idle",
    icon: ICON.pause,
    label: "Not running",
    headline: "This account is not running",
    detail:
      "The account is disabled or failed to start. Open the integration page to " +
      "enable it or read why it stopped.",
    action: { label: "Open integration page", act: "settings" },
  },
};

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** Escape anything that came from storage, TextNow or an error message. */
const esc = (value) =>
  String(value === undefined || value === null ? "" : value).replace(
    /[&<>"']/g,
    (char) => ESCAPES[char]
  );

const svg = (path, size = 20) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true" focusable="false"><path d="${path}"/></svg>`;

/** Strip a phone number down to the ten digits TextNow expects. */
const phoneDigits = (value) => {
  let digits = String(value || "").replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("1")) digits = digits.slice(1);
  return digits;
};

const formatPhone = (value) => {
  const digits = phoneDigits(value);
  if (digits.length !== 10) return String(value || "");
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
};

/** Give each contact a stable avatar colour so the list is easy to scan. */
const avatarHue = (seed) => {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) % 360;
  }
  return hash;
};

const initials = (name) => {
  const parts = String(name || "?")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

const relativeTime = (iso) => {
  if (!iso) return "not yet";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "not yet";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds} seconds ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return minutes === 1 ? "a minute ago" : `${minutes} minutes ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return hours === 1 ? "an hour ago" : `${hours} hours ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
};

/** The other direction from relativeTime: a date that has not arrived yet. */
const timeUntil = (iso) => {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.round((then - Date.now()) / 60000);
  if (minutes <= 0) return "due now";
  if (minutes < 60) return "in under an hour";
  const hours = Math.round(minutes / 60);
  if (hours < 24) return hours === 1 ? "in about an hour" : `in about ${hours} hours`;
  const days = Math.round(hours / 24);
  return days === 1 ? "tomorrow" : `in ${days} days`;
};

const dayPhrase = (days) => (days === 1 ? "a day" : `${days} days`);

const everyPhrase = (seconds) => {
  if (!seconds) return "paused";
  if (seconds < 60) return `every ${seconds} seconds`;
  const minutes = Math.round(seconds / 60);
  return minutes === 1 ? "every minute" : `every ${minutes} minutes`;
};

const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

class TextNowPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._panelConfig = {};
    this._entries = [];
    this._contacts = {};
    this._tab = "contacts";
    this._loading = true;
    this._loadError = "";
    this._narrow = false;
    this._compact = false;
    this._hassNarrow = false;
    // Values typed into forms, kept across re-renders so a background
    // refresh never eats what someone is halfway through writing.
    this._draft = {};
    this._addOpen = {};
    this._busy = {};
    this._dialog = null;
    this._snack = null;
    this._snackTimer = null;
    this._pollTimer = null;
    this._onKeyDown = this._onKeyDown.bind(this);
  }

  set hass(hass) {
    const first = this._hass === null;
    this._hass = hass;
    if (first) this._load();
  }

  set panel(panel) {
    this._panelConfig = (panel && panel.config) || {};
  }

  set narrow(value) {
    // Home Assistant reports whether its own layout is narrow; the panel also
    // measures itself, because the sidebar collapses independently.
    if (this._hassNarrow === !!value) return;
    this._hassNarrow = !!value;
    if (this.shadowRoot.childElementCount) this._render();
  }

  get _docsUrl() {
    return this._panelConfig.help_url || DOCS_FALLBACK;
  }

  connectedCallback() {
    this._render();
    this.addEventListener("keydown", this._onKeyDown);
    // The sidebar can be collapsed independently of the window size, so the
    // panel measures itself rather than trusting a media query.
    this._observer = new ResizeObserver(() => {
      const width = this.offsetWidth || this.getBoundingClientRect().width;
      this._setWidth(width);
    });
    this._observer.observe(this);
    this._pollTimer = window.setInterval(() => this._refreshQuietly(), POLL_MS);
  }

  disconnectedCallback() {
    this.removeEventListener("keydown", this._onKeyDown);
    if (this._observer) {
      this._observer.disconnect();
      this._observer = null;
    }
    if (this._pollTimer) {
      window.clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
    if (this._snackTimer) window.clearTimeout(this._snackTimer);
  }

  _setWidth(width) {
    const narrow = width <= 870;
    const compact = width <= 560;
    if (this._narrow === narrow && this._compact === compact) return;
    this._narrow = narrow;
    this._compact = compact;
    if (this.shadowRoot.childElementCount) this._render();
  }

  // ---------------------------------------------------------------- data

  async _load() {
    this._loading = true;
    this._render();
    await this._fetchEntries();
    this._loading = false;
    this._render();
  }

  /** Refresh in the background without flashing a spinner over the page. */
  async _refreshQuietly() {
    if (!this._hass || this._dialog || this._loading) return;
    const before = this._signature();
    await this._fetchEntries();
    // Re-rendering only when something actually changed keeps the page still
    // while someone is reading or typing.
    if (this._signature() !== before) this._render();
  }

  _signature() {
    return JSON.stringify({ e: this._entries, c: this._contacts, x: this._loadError });
  }

  async _fetchEntries() {
    if (!this._hass) return;
    try {
      const entries = (await this._hass.callWS({ type: "textnow/get_entries" })) || [];
      this._entries = entries;
      this._loadError = "";
      await Promise.all(
        entries.map(async (entry) => {
          this._contacts[entry.entry_id] = await this._fetchContacts(entry.entry_id);
        })
      );
    } catch (err) {
      this._loadError = this._reason(err);
      this._entries = [];
    }
  }

  async _fetchContacts(entryId) {
    try {
      return (
        (await this._hass.callWS({ type: "textnow/contacts_list", entry_id: entryId })) ||
        []
      );
    } catch (err) {
      console.error("TextNow: could not load contacts", err);
      return this._contacts[entryId] || [];
    }
  }

  _reason(err) {
    if (!err) return "Unknown error";
    return err.message || err.error || String(err);
  }

  async _call(key, work, { success, failure } = {}) {
    this._busy[key] = true;
    this._render();
    try {
      const result = await work();
      if (success) this._toast(success, "ok");
      return result;
    } catch (err) {
      this._toast(`${failure || "That did not work"}: ${this._reason(err)}`, "bad");
      return null;
    } finally {
      delete this._busy[key];
      this._render();
    }
  }

  async _addContact(entryId) {
    const name = (this._draft[`add:${entryId}:name`] || "").trim();
    const phone = (this._draft[`add:${entryId}:phone`] || "").trim();
    if (!name || phoneDigits(phone).length !== 10) {
      this._draft[`add:${entryId}:error`] = !name
        ? "Enter a name for this contact."
        : "Enter a 10-digit phone number, for example (555) 123-4567.";
      this._render();
      return;
    }
    delete this._draft[`add:${entryId}:error`];

    const added = await this._call(
      `add:${entryId}`,
      () =>
        this._hass.callWS({
          type: "textnow/contacts_add",
          entry_id: entryId,
          name,
          phone,
        }),
      { success: `${name} was added`, failure: "Could not add this contact" }
    );

    if (added) {
      delete this._draft[`add:${entryId}:name`];
      delete this._draft[`add:${entryId}:phone`];
      this._addOpen[entryId] = false;
      this._contacts[entryId] = await this._fetchContacts(entryId);
      this._render();
    }
  }

  async _saveContact() {
    const dialog = this._dialog;
    const name = (this._draft["edit:name"] || "").trim();
    const phone = (this._draft["edit:phone"] || "").trim();
    if (!name || phoneDigits(phone).length !== 10) {
      this._draft["edit:error"] = !name
        ? "Enter a name for this contact."
        : "Enter a 10-digit phone number, for example (555) 123-4567.";
      this._render();
      return;
    }
    delete this._draft["edit:error"];

    const saved = await this._call(
      "edit",
      () =>
        this._hass.callWS({
          type: "textnow/contacts_update",
          entry_id: dialog.entryId,
          contact_id: dialog.contactId,
          name,
          phone,
        }),
      { success: "Contact saved", failure: "Could not save this contact" }
    );

    if (saved) {
      this._contacts[dialog.entryId] = await this._fetchContacts(dialog.entryId);
      this._closeDialog();
    }
  }

  async _deleteContact() {
    const dialog = this._dialog;
    const done = await this._call(
      "delete",
      () =>
        this._hass.callWS({
          type: "textnow/contacts_delete",
          entry_id: dialog.entryId,
          contact_id: dialog.contactId,
        }),
      { success: `${dialog.name} was removed`, failure: "Could not remove this contact" }
    );

    if (done) {
      this._contacts[dialog.entryId] = await this._fetchContacts(dialog.entryId);
      this._closeDialog();
    }
  }

  async _sendMessage() {
    const dialog = this._dialog;
    const message = (this._draft["send:text"] || "").trim();
    if (!message) {
      this._draft["send:error"] = "Write a message first.";
      this._render();
      return;
    }
    delete this._draft["send:error"];

    const sent = await this._call(
      "send",
      () =>
        this._hass.callWS({
          type: "textnow/send_test",
          entry_id: dialog.entryId,
          contact_id: dialog.contactId,
          message,
        }),
      { success: `Message sent to ${dialog.name}`, failure: "Could not send" }
    );

    if (sent) {
      delete this._draft["send:text"];
      this._closeDialog();
      return;
    }

    // A send fails for a reason the status should now be showing, such as a
    // session TextNow has just refused, so pick that up rather than leaving
    // the panel claiming everything is fine.
    await this._fetchEntries();
    this._render();
  }

  async _checkNow(entryId) {
    await this._call(
      `check:${entryId}`,
      () => this._hass.callWS({ type: "textnow/refresh", entry_id: entryId }),
      { failure: "Could not check for messages" }
    );
    await this._fetchEntries();
    const entry = this._entries.find((item) => item.entry_id === entryId);
    if (entry && entry.status === "connected") {
      this._toast("Connection is working", "ok");
    } else if (entry) {
      this._toast(STATUS_COPY[this._statusOf(entry)].headline, "warn");
    }
    this._render();
  }

  /**
   * Ask Home Assistant to open the sign-in form, then go to where it shows.
   *
   * Sending the user to the integrations page on its own only works when a
   * prompt happens to be open there already.
   */
  async _startReauth(entryId) {
    try {
      await this._hass.callWS({ type: "textnow/start_reauth", entry_id: entryId });
    } catch (err) {
      console.error("TextNow: could not start the sign-in", err);
    }
    window.location.assign(INTEGRATION_PAGE);
  }

  async _sendKeepalive(entryId) {
    const entry = this._entries.find((item) => item.entry_id === entryId);
    const phone = entry && entry.keepalive ? formatPhone(entry.keepalive.phone) : "";
    const sent = await this._call(
      `keepalive:${entryId}`,
      () => this._hass.callWS({ type: "textnow/keepalive_now", entry_id: entryId }),
      {
        success: phone ? `Sent a message to ${phone}` : "Message sent",
        failure: "Could not send the message",
      }
    );

    if (sent) {
      await this._fetchEntries();
      this._render();
    }
  }

  // ------------------------------------------------------------ dialogs

  _openDialog(dialog) {
    this._dialog = dialog;
    if (dialog.kind === "edit") {
      this._draft["edit:name"] = dialog.name;
      this._draft["edit:phone"] = formatPhone(dialog.phone);
      delete this._draft["edit:error"];
    }
    if (dialog.kind === "send") {
      this._draft["send:text"] = "";
      delete this._draft["send:error"];
    }
    this._render();
    const field = this.shadowRoot.querySelector("[data-autofocus]");
    if (field) field.focus();
  }

  _closeDialog() {
    this._dialog = null;
    this._render();
  }

  _onKeyDown(event) {
    if (event.key === "Escape" && this._dialog) {
      event.stopPropagation();
      this._closeDialog();
    }
  }

  _toast(message, tone = "ok") {
    this._snack = { message, tone };
    this._render();
    if (this._snackTimer) window.clearTimeout(this._snackTimer);
    this._snackTimer = window.setTimeout(() => {
      this._snack = null;
      this._render();
    }, 5000);
  }

  // ----------------------------------------------------------- rendering

  _render() {
    const active = this.shadowRoot.activeElement;
    const focusKey = active && active.dataset ? active.dataset.field : null;
    const caret = active && active.selectionStart !== undefined ? active.selectionStart : null;

    this.shadowRoot.innerHTML = `
      ${this._styles()}
      <div class="app ${this._narrow || this._hassNarrow ? "narrow" : ""} ${
      this._compact ? "compact" : ""
    }">
        ${this._header()}
        ${this._tabs()}
        <main class="content" role="main">
          <div class="page">${this._page()}</div>
        </main>
      </div>
      ${this._dialogMarkup()}
      ${this._snackMarkup()}
    `;

    if (focusKey) {
      const field = this.shadowRoot.querySelector(`[data-field="${focusKey}"]`);
      if (field) {
        field.focus();
        if (caret !== null && field.setSelectionRange) {
          try {
            field.setSelectionRange(caret, caret);
          } catch (err) {
            /* not a text field */
          }
        }
      }
    }

    this._bind();
  }

  _header() {
    const summary = this._overallStatus();
    return `
      <header class="bar">
        <button class="icon-btn menu-btn" data-act="menu" aria-label="Show sidebar">
          ${svg(ICON.menu, 24)}
        </button>
        <span class="logo">
          ${svg(ICON.message, 20)}
          <img src="${LOGO_URL}" alt="" onerror="this.remove()" />
        </span>
        <div class="titles">
          <h1>TextNow</h1>
          <p>${esc(this._subtitle())}</p>
        </div>
        ${
          summary
            ? `<button class="pill pill-${summary.tone}" data-act="tab" data-tab="status"
                 title="See connection details">
                 <span class="dot"></span>${esc(summary.label)}
               </button>`
            : ""
        }
        <button class="icon-btn" data-act="reload" aria-label="Refresh this page"
          title="Refresh this page">${svg(ICON.refresh, 22)}</button>
      </header>
    `;
  }

  _subtitle() {
    if (this._loading) return "Loading…";
    if (this._entries.length === 0) return "No account connected yet";
    const contacts = Object.values(this._contacts).reduce(
      (total, list) => total + (list || []).length,
      0
    );
    if (this._entries.length === 1) {
      return `${plural(contacts, "contact")}`;
    }
    return `${plural(this._entries.length, "account")} · ${plural(contacts, "contact")}`;
  }

  /** The worst status across accounts, which is the one worth surfacing. */
  _overallStatus() {
    if (this._loading || this._entries.length === 0) return null;
    const order = ["reauth_required", "disabled", "offline", "connected"];
    const worst = order.find((status) =>
      this._entries.some((entry) => this._statusOf(entry) === status)
    );
    const copy = STATUS_COPY[worst || "connected"];
    return { tone: copy.tone, label: copy.label };
  }

  _statusOf(entry) {
    if (entry.status && STATUS_COPY[entry.status]) return entry.status;
    // Older backends only sent booleans.
    if (entry.needs_reauth) return "reauth_required";
    if (!entry.loaded) return "disabled";
    return entry.connected ? "connected" : "offline";
  }

  _tabs() {
    const tab = (id, label, icon) => `
      <button class="tab ${this._tab === id ? "active" : ""}" data-act="tab" data-tab="${id}"
        role="tab" aria-selected="${this._tab === id}">
        ${svg(icon, 18)}<span>${label}</span>
      </button>`;
    return `
      <nav class="tabs" role="tablist">
        ${tab("contacts", "Contacts", ICON.people)}
        ${tab("status", "Connection", ICON.check)}
        ${tab("help", "Help", ICON.help)}
      </nav>
    `;
  }

  _page() {
    if (this._loading) return this._skeleton();
    if (this._loadError) {
      return this._noticeCard(
        "bad",
        ICON.alert,
        "Could not load the TextNow panel",
        this._loadError,
        `<button class="btn" data-act="reload">Try again</button>`
      );
    }
    if (this._entries.length === 0 && this._tab !== "help") return this._welcome();
    if (this._tab === "status") return this._statusPage();
    if (this._tab === "help") return this._helpPage();
    return this._contactsPage();
  }

  _skeleton() {
    const row = `<div class="sk-row"><div class="sk sk-avatar"></div>
      <div class="sk-lines"><div class="sk sk-line"></div><div class="sk sk-line short"></div></div></div>`;
    return `<div class="card">${row}${row}${row}</div>`;
  }

  _welcome() {
    return `
      <section class="card hero">
        <div class="hero-art">${svg(ICON.message, 40)}</div>
        <h2>Send and receive texts from Home Assistant</h2>
        <p class="lede">
          Connect your TextNow account once and you can text your contacts from
          automations, and trigger automations from the texts they send back.
        </p>
        <ol class="steps compact">
          <li><span class="num">1</span><div><strong>Sign in to TextNow</strong>
            in a desktop browser.</div></li>
          <li><span class="num">2</span><div><strong>Copy one request</strong>
            from the browser so Home Assistant can use the same session.</div></li>
          <li><span class="num">3</span><div><strong>Paste it here</strong> —
            the username and cookies are read from the paste for you.</div></li>
        </ol>
        <div class="hero-actions">
          <button class="btn primary lg" data-act="add-account">
            ${svg(ICON.plus, 20)} Connect TextNow
          </button>
          <button class="btn" data-act="tab" data-tab="help">
            ${svg(ICON.help, 20)} Show me how
          </button>
        </div>
      </section>
    `;
  }

  // --------------------------------------------------------- contacts tab

  _contactsPage() {
    const alerts = this._entries
      .filter((entry) => this._statusOf(entry) !== "connected")
      .map((entry) => this._alertCard(entry))
      .join("");

    const healthy = this._entries.every(
      (entry) => this._statusOf(entry) === "connected"
    );

    const strip = healthy ? this._healthStrip() : "";

    const accounts = this._entries
      .map((entry) => this._accountSection(entry))
      .join("");

    return `${strip}${alerts}${accounts}`;
  }

  _healthStrip() {
    const entry = this._entries[0];
    const checked = relativeTime(entry.last_success);
    const busy = this._busy[`check:${entry.entry_id}`];
    return `
      <div class="strip">
        <span class="badge ok">${svg(ICON.check, 16)}Connected</span>
        <span class="strip-text">Last checked ${esc(checked)}</span>
        <button class="btn quiet sm" data-act="check" data-entry="${esc(entry.entry_id)}"
          ${busy ? "disabled" : ""}>${busy ? "Checking…" : "Check now"}</button>
      </div>
    `;
  }

  _alertCard(entry) {
    const copy = STATUS_COPY[this._statusOf(entry)];
    const action = copy.action
      ? `<button class="btn primary" data-act="${copy.action.act}"
           data-entry="${esc(entry.entry_id)}">${copy.action.label}</button>`
      : "";
    const title =
      this._entries.length > 1 ? `${copy.headline} (${entry.title})` : copy.headline;
    return this._noticeCard(
      copy.tone,
      copy.icon,
      title,
      copy.detail,
      `${action}<button class="btn" data-act="tab" data-tab="help">What does this mean?</button>`
    );
  }

  /** Title and body are plain text; this escapes them. */
  _noticeCard(tone, icon, title, body, actions) {
    return `
      <section class="card notice tone-${tone}" role="${tone === "ok" ? "status" : "alert"}">
        <div class="notice-icon">${svg(icon, 24)}</div>
        <div class="notice-body">
          <h2>${esc(title)}</h2>
          <p>${esc(body)}</p>
          ${actions ? `<div class="row gap">${actions}</div>` : ""}
        </div>
      </section>
    `;
  }

  _accountSection(entry) {
    const contacts = this._contacts[entry.entry_id] || [];
    const multiple = this._entries.length > 1;
    const open = !!this._addOpen[entry.entry_id];

    const copy = STATUS_COPY[this._statusOf(entry)];

    return `
      <section class="card">
        <div class="card-head">
          <div>
            <h2>
              ${multiple ? esc(entry.title) : "Contacts"}
              ${
                multiple
                  ? `<span class="dot dot-${copy.tone}" title="${esc(
                      copy.label
                    )}" aria-label="${esc(copy.label)}"></span>`
                  : ""
              }
            </h2>
            <p class="sub">${
              contacts.length
                ? `${plural(contacts.length, "contact")} · each one gets its own sensor`
                : "Add the people you want to text"
            }</p>
          </div>
          ${
            open
              ? ""
              : `<button class="btn primary" data-act="toggle-add"
                   data-entry="${esc(entry.entry_id)}" aria-label="Add contact">
                   ${svg(ICON.plus, 20)}<span class="hide-compact">Add contact</span>
                 </button>`
          }
        </div>

        ${open ? this._addForm(entry) : ""}

        ${
          contacts.length
            ? `<ul class="list">${contacts
                .map((contact) => this._contactRow(entry, contact))
                .join("")}</ul>`
            : this._emptyContacts(entry)
        }
      </section>
    `;
  }

  _emptyContacts(entry) {
    if (this._addOpen[entry.entry_id]) return "";
    return `
      <div class="empty">
        ${svg(ICON.people, 32)}
        <p><strong>No contacts yet</strong></p>
        <p class="sub">A contact gives you a sensor that holds their last message,
          and a name you can use in automations.</p>
        <button class="btn primary" data-act="toggle-add" data-entry="${esc(entry.entry_id)}">
          ${svg(ICON.plus, 20)} Add your first contact
        </button>
      </div>
    `;
  }

  _addForm(entry) {
    const id = entry.entry_id;
    const error = this._draft[`add:${id}:error`];
    const busy = this._busy[`add:${id}`];
    return `
      <form class="form" data-act="submit-add" data-entry="${esc(id)}">
        <div class="fields">
          <label class="field">
            <span>Name</span>
            <input data-field="add:${esc(id)}:name" data-autofocus type="text"
              placeholder="Sam" autocomplete="off"
              value="${esc(this._draft[`add:${id}:name`] || "")}" />
            <small>Used for the sensor name and in automations.</small>
          </label>
          <label class="field">
            <span>Phone number</span>
            <input data-field="add:${esc(id)}:phone" data-phone type="tel"
              inputmode="tel" placeholder="(555) 123-4567" autocomplete="off"
              value="${esc(this._draft[`add:${id}:phone`] || "")}" />
            <small>10 digits, US numbers only.</small>
          </label>
        </div>
        ${error ? `<p class="field-error">${esc(error)}</p>` : ""}
        <div class="row gap end">
          <button type="button" class="btn" data-act="toggle-add" data-entry="${esc(id)}">Cancel</button>
          <button type="submit" class="btn primary" ${busy ? "disabled" : ""}>
            ${busy ? "Adding…" : "Add contact"}
          </button>
        </div>
      </form>
    `;
  }

  _contactRow(entry, contact) {
    const hue = avatarHue(contact.id || contact.name || "");
    // Gated on the account running, not on the reported status. A status can
    // be stale, and disabling a control that would have worked is worse than
    // letting the send fail with the real reason.
    const canSend = entry.loaded !== false;
    return `
      <li class="item">
        <span class="avatar" style="background: hsl(${hue} 52% 42%)" aria-hidden="true">
          ${esc(initials(contact.name))}
        </span>
        <div class="item-text">
          <div class="item-name">${esc(contact.name)}</div>
          <div class="item-sub">
            <span class="phone">${esc(formatPhone(contact.phone))}</span>
          </div>
        </div>
        <div class="item-actions">
          <button class="btn sm" data-act="send-open" data-entry="${esc(entry.entry_id)}"
            data-contact="${esc(contact.id)}" ${canSend ? "" : "disabled"}
            title="${canSend ? "Send a message" : "Available once this account is running"}">
            ${svg(ICON.send, 18)}<span class="hide-narrow">Message</span>
          </button>
          <button class="icon-btn" data-act="edit-open" data-entry="${esc(entry.entry_id)}"
            data-contact="${esc(contact.id)}" aria-label="Edit ${esc(contact.name)}"
            title="Edit">${svg(ICON.pencil, 18)}</button>
          <button class="icon-btn danger" data-act="delete-open" data-entry="${esc(entry.entry_id)}"
            data-contact="${esc(contact.id)}" aria-label="Remove ${esc(contact.name)}"
            title="Remove">${svg(ICON.trash, 18)}</button>
        </div>
      </li>
    `;
  }

  // ----------------------------------------------------------- status tab

  _statusPage() {
    return this._entries.map((entry) => this._statusCard(entry)).join("") + this._aboutCard();
  }

  _statusCard(entry) {
    const status = this._statusOf(entry);
    const copy = STATUS_COPY[status];
    const contacts = (this._contacts[entry.entry_id] || []).length;
    const busy = this._busy[`check:${entry.entry_id}`];
    const interval = entry.current_interval || entry.polling_interval;

    const rows = [
      ["Account", entry.account ? `@${entry.account}` : entry.title],
      ["Contacts", plural(contacts, "contact")],
      [
        "Checks for messages",
        status === "reauth_required" ? "paused until you sign in again" : everyPhrase(interval),
      ],
      ["Last successful check", relativeTime(entry.last_success)],
    ];

    return `
      <section class="card">
        <div class="status-head tone-${copy.tone}">
          <div class="status-icon">${svg(copy.icon, 28)}</div>
          <div>
            <h2>${esc(copy.headline)}</h2>
            <p class="sub">${esc(entry.title)}</p>
          </div>
        </div>
        ${copy.detail ? `<p class="explain">${copy.detail}</p>` : ""}
        <dl class="facts">
          ${rows
            .map(
              ([label, value]) =>
                `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`
            )
            .join("")}
        </dl>
        ${
          entry.last_error
            ? `<details class="tech"><summary>Technical details</summary>
                 <code>${esc(entry.last_error)}</code></details>`
            : ""
        }
        ${this._keepaliveBlock(entry, status)}
        <div class="row gap">
          ${
            copy.action && copy.action.act === "fix"
              ? `<button class="btn primary" data-act="fix" data-entry="${esc(
                  entry.entry_id
                )}">Fix this now</button>`
              : ""
          }
          <button class="btn" data-act="check" data-entry="${esc(entry.entry_id)}"
            ${busy ? "disabled" : ""}>${svg(ICON.refresh, 18)} ${
      busy ? "Checking…" : "Check now"
    }</button>
          <button class="btn" data-act="settings">${svg(ICON.cog, 18)} Settings</button>
        </div>
      </section>
    `;
  }

  /**
   * TextNow reclaims a number nobody uses, so this is a real risk to explain
   * rather than a setting to bury.
   */
  _keepaliveBlock(entry, status) {
    const keepalive = entry.keepalive || {};
    const busy = this._busy[`keepalive:${entry.entry_id}`];

    if (!keepalive.enabled) {
      return `
        <div class="keepalive off">
          <div class="ka-icon">${svg(ICON.shield, 22)}</div>
          <div class="ka-text">
            <strong>Your number could be reclaimed</strong>
            <p class="sub">TextNow takes a number back if it sits unused. Home
              Assistant can send one short text to a number you choose, such as your
              own phone, whenever nothing else has gone out for a while.</p>
          </div>
          <button class="btn sm" data-act="settings">Turn this on</button>
        </div>
      `;
    }

    // Nothing can be sent while the connection is down, so claiming the
    // number is safe would be a lie at the one time it is most at risk.
    if (status !== "connected") {
      return `
        <div class="keepalive off">
          <div class="ka-icon">${svg(ICON.shield, 22)}</div>
          <div class="ka-text">
            <strong>Keeping your number in use is paused</strong>
            <p class="sub">Nothing can be sent until this connection works again,
              and TextNow takes back a number that goes unused. Fixing the
              connection is what protects the number.</p>
          </div>
        </div>
      `;
    }

    const lastUsed = keepalive.last_outbound
      ? `Last message went out ${relativeTime(keepalive.last_outbound)}.`
      : "Nothing has been sent yet, so the first one goes out shortly.";
    const due = timeUntil(keepalive.due_at);

    return `
      <div class="keepalive">
        <div class="ka-icon ok">${svg(ICON.shield, 22)}</div>
        <div class="ka-text">
          <strong>Your number is being kept active</strong>
          <p class="sub">A short text goes to ${esc(
            formatPhone(keepalive.phone)
          )} if nothing else is sent for ${esc(dayPhrase(keepalive.days))}.
            ${esc(lastUsed)}${due ? ` Next one ${esc(due)}.` : ""}</p>
        </div>
        <button class="btn sm" data-act="keepalive" data-entry="${esc(entry.entry_id)}"
          ${busy ? "disabled" : ""}
          title="Send the message now instead of waiting">${
            busy ? "Sending…" : "Send one now"
          }</button>
      </div>
    `;
  }

  _aboutCard() {
    const version = this._panelConfig.version;
    return `
      <section class="card about">
        <div class="row gap wrap">
          <button class="btn" data-act="add-account">${svg(ICON.plus, 18)} Add another account</button>
          <a class="btn" href="${esc(this._docsUrl)}" target="_blank" rel="noreferrer">
            ${svg(ICON.external, 18)} Documentation
          </a>
        </div>
        ${version ? `<p class="sub center">TextNow integration ${esc(version)}</p>` : ""}
      </section>
    `;
  }

  // ------------------------------------------------------------- help tab

  _helpPage() {
    return `
      <section class="card">
        <h2>Connecting your account</h2>
        <p class="lede">
          TextNow has no password option for other apps, so Home Assistant borrows
          the session from a browser you are already signed in to. It sounds
          technical, but it is one search, one right-click and one paste — the
          screenshots below show exactly what to look for.
        </p>
        <ol class="steps">
          <li><span class="num">1</span><div>
            <strong>Sign in to textnow.com</strong> in Chrome or Edge on a
            computer. Phones cannot do the next step.</div></li>
          <li><span class="num">2</span><div>
            <strong>Press F12.</strong> A panel opens beside the page. Click the
            <strong>Network</strong> tab at the top of it.</div></li>
          <li><span class="num">3</span><div>
            <strong>Reload the page, then press Ctrl+F</strong> (⌘F on a Mac) and
            search for <code>messaging</code>. Click the row of that name in the
            list. It is the right one when the <strong>Headers</strong> panel shows
            <code>https://www.textnow.com/messaging</code> and
            <strong>200 OK</strong>.
            <figure class="shot">
              <a href="${HELP_FIND_URL}" target="_blank" rel="noreferrer">
                <img src="${HELP_FIND_URL}" alt="The Network tab search box with messaging typed in, the matching request selected in the list, and its Headers panel showing a 200 OK response" loading="lazy">
              </a>
              <figcaption>Click to see it full size</figcaption>
            </figure></div></li>
          <li><span class="num">4</span><div>
            <strong>Right-click that row</strong> and choose <strong>Copy</strong> →
            <strong>Copy as cURL (bash)</strong> — the circled entry below. The
            Windows <em>(cmd)</em> version works too.
            <figure class="shot">
              <a href="${HELP_COPY_URL}" target="_blank" rel="noreferrer">
                <img src="${HELP_COPY_URL}" alt="The right-click menu on the messaging request, with Copy as cURL (bash) circled inside the Copy submenu" loading="lazy">
              </a>
              <figcaption>Click to see it full size</figcaption>
            </figure></div></li>
          <li><span class="num">5</span><div>
            <strong>Paste it into the Cookies box</strong> when you add the account
            here. Leave the username blank; it is read from the paste.</div></li>
        </ol>
        <div class="row gap">
          <button class="btn primary" data-act="add-account">${svg(ICON.plus, 20)} Add an account</button>
          <a class="btn" href="${esc(this._docsUrl)}" target="_blank" rel="noreferrer">
            ${svg(ICON.external, 18)} Full guide with screenshots
          </a>
        </div>
        <p class="note">
          That paste contains your live TextNow session. Treat it like a password:
          paste it straight into Home Assistant and nowhere else.
        </p>
      </section>

      <section class="card">
        <h2>When it says a sign-in is needed</h2>
        <p>
          TextNow signs old sessions out eventually. Nothing is broken and nothing
          is lost when that happens — your contacts, sensors and automations stay
          exactly as they are.
        </p>
        <p>
          Home Assistant stops checking for messages so it is not hammering a
          session that has been refused, shows a repair notice, and waits for a
          fresh cookie line. Repeat the five steps above, then press
          <strong>Fix this now</strong> on the Connection tab and paste.
        </p>
      </section>

      <section class="card">
        <h2>Checking that it works</h2>
        <p>
          Add a contact on the Contacts tab, then press <strong>Message</strong>
          next to their name and send yourself a short text. If it arrives, sending
          works. Reply to it from the other phone and that contact's sensor will
          update, which is what automations watch for.
        </p>
      </section>

      <section class="card">
        <h2>Keeping your number</h2>
        <p>
          A TextNow number is free, and the catch is that TextNow takes it back if
          nobody uses it. Losing it means losing the number your contacts reply to
          and every automation pointed at it, so it is worth guarding.
        </p>
        <p>
          Receiving messages does not count — only sending does. If your automations
          text people every few days you are already fine. If they only send during
          a power cut or a leak, the number can quietly expire between emergencies,
          which is exactly when you need it.
        </p>
        <p>
          To cover that, open <strong>Settings</strong> on the Connection tab, choose
          <strong>Keep the number in use</strong>, and pick a number to text, usually
          your own phone. Home Assistant then sends one short message only when
          nothing else has gone out for a few days, and the Connection tab shows when
          the next one is due.
        </p>
      </section>

      <section class="card">
        <h2>Why it checks on a timer</h2>
        <p>
          TextNow offers no way to notify Home Assistant when a message arrives, so
          the integration asks every ${esc(
            everyPhrase(
              (this._entries[0] && (this._entries[0].polling_interval || 30)) || 30
            ).replace("every ", "")
          )} by default. Checking
          more often delivers messages sooner but makes more requests; you can change
          it in the integration options.
        </p>
      </section>
    `;
  }

  // ------------------------------------------------------------- dialogs

  _dialogMarkup() {
    const dialog = this._dialog;
    if (!dialog) return "";

    let body = "";
    let footer = "";
    let title = "";

    if (dialog.kind === "send") {
      const text = this._draft["send:text"] || "";
      const error = this._draft["send:error"];
      title = `Message ${esc(dialog.name)}`;
      body = `
        <p class="sub">To ${esc(formatPhone(dialog.phone))}</p>
        <label class="field">
          <span>Message</span>
          <textarea data-field="send:text" data-autofocus rows="4"
            maxlength="${MESSAGE_LIMIT}" placeholder="Hello from Home Assistant">${esc(text)}</textarea>
          <small>${MESSAGE_LIMIT - text.length} characters left</small>
        </label>
        ${error ? `<p class="field-error">${esc(error)}</p>` : ""}
      `;
      footer = `
        <button class="btn" data-act="dialog-close">Cancel</button>
        <button class="btn primary" data-act="send-confirm" ${this._busy.send ? "disabled" : ""}>
          ${svg(ICON.send, 18)} ${this._busy.send ? "Sending…" : "Send"}
        </button>`;
    }

    if (dialog.kind === "edit") {
      const error = this._draft["edit:error"];
      title = "Edit contact";
      body = `
        <div class="fields">
          <label class="field"><span>Name</span>
            <input data-field="edit:name" data-autofocus type="text"
              value="${esc(this._draft["edit:name"] || "")}" /></label>
          <label class="field"><span>Phone number</span>
            <input data-field="edit:phone" data-phone type="tel" inputmode="tel"
              value="${esc(this._draft["edit:phone"] || "")}" /></label>
        </div>
        ${error ? `<p class="field-error">${esc(error)}</p>` : ""}
      `;
      footer = `
        <button class="btn" data-act="dialog-close">Cancel</button>
        <button class="btn primary" data-act="edit-confirm" ${this._busy.edit ? "disabled" : ""}>
          ${this._busy.edit ? "Saving…" : "Save"}
        </button>`;
    }

    if (dialog.kind === "delete") {
      title = `Remove ${esc(dialog.name)}?`;
      body = `<p>Their sensor is removed from Home Assistant. Any automation that
        uses it will stop working until you point it somewhere else. Messages
        already received are not deleted from TextNow.</p>`;
      footer = `
        <button class="btn" data-act="dialog-close">Keep contact</button>
        <button class="btn danger" data-act="delete-confirm" ${this._busy.delete ? "disabled" : ""}>
          ${this._busy.delete ? "Removing…" : "Remove"}
        </button>`;
    }

    return `
      <div class="scrim" data-act="dialog-close"></div>
      <div class="dialog" role="dialog" aria-modal="true" aria-label="${title}">
        <div class="dialog-head">
          <h2>${title}</h2>
          <button class="icon-btn" data-act="dialog-close" aria-label="Close">
            ${svg(ICON.close, 20)}
          </button>
        </div>
        <div class="dialog-body">${body}</div>
        <div class="dialog-foot">${footer}</div>
      </div>
    `;
  }

  _snackMarkup() {
    if (!this._snack) return "";
    const { message, tone } = this._snack;
    const icon = tone === "ok" ? ICON.check : tone === "warn" ? ICON.warning : ICON.alert;
    return `
      <div class="snack tone-${tone}" role="status" aria-live="polite">
        ${svg(icon, 18)}<span>${esc(message)}</span>
        <button class="icon-btn tiny" data-act="snack-close" aria-label="Dismiss">
          ${svg(ICON.close, 16)}
        </button>
      </div>
    `;
  }

  // -------------------------------------------------------------- events

  _bind() {
    // The shadow root survives re-renders, so these delegated listeners are
    // attached once instead of stacking up on every render.
    if (this._bound) return;
    this._bound = true;
    const root = this.shadowRoot;

    root.addEventListener("click", (event) => {
      const target = event.target.closest("[data-act]");
      if (!target || target.tagName === "FORM") return;
      const { act, entry, contact, tab } = target.dataset;
      if (target.tagName !== "A") event.preventDefault();
      this._handle(act, { entryId: entry, contactId: contact, tab });
    });

    root.addEventListener("submit", (event) => {
      const form = event.target.closest("form[data-act]");
      if (!form) return;
      event.preventDefault();
      if (form.dataset.act === "submit-add") this._addContact(form.dataset.entry);
    });

    root.addEventListener("input", (event) => {
      const field = event.target;
      if (!field.dataset || !field.dataset.field) return;
      if (field.dataset.phone !== undefined) {
        const digits = phoneDigits(field.value).slice(0, 10);
        field.value = digits.length === 10 ? formatPhone(digits) : field.value;
      }
      this._draft[field.dataset.field] = field.value;

      // Typing must not re-render, or the caret would jump, so the pieces
      // that have to keep up with each keystroke are updated in place.
      const counter = field.parentElement.querySelector("small");
      if (counter && field.dataset.field === "send:text") {
        counter.textContent = `${MESSAGE_LIMIT - field.value.length} characters left`;
      }

      // A complaint about what was typed is stale as soon as it is being
      // fixed. Submitting brings it back if the value is still wrong.
      const holder = field.closest("form") || field.closest(".dialog-body");
      const shown = holder && holder.querySelector(".field-error");
      if (shown) {
        shown.remove();
        Object.keys(this._draft)
          .filter((key) => key.endsWith(":error"))
          .forEach((key) => delete this._draft[key]);
      }
    });
  }

  _handle(act, { entryId, contactId, tab } = {}) {
    const contactOf = (id, cid) =>
      (this._contacts[id] || []).find((item) => item.id === cid) || {};

    switch (act) {
      case "menu":
        this.dispatchEvent(
          new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true })
        );
        break;
      case "tab":
        this._tab = tab;
        this._render();
        break;
      case "reload":
        this._load();
        break;
      case "check":
        this._checkNow(entryId);
        break;
      case "keepalive":
        this._sendKeepalive(entryId);
        break;
      case "fix":
        this._startReauth(entryId);
        break;
      case "settings":
        window.location.assign(INTEGRATION_PAGE);
        break;
      case "add-account":
        window.location.assign(ADD_ACCOUNT_PAGE);
        break;
      case "toggle-add":
        this._addOpen[entryId] = !this._addOpen[entryId];
        delete this._draft[`add:${entryId}:error`];
        this._render();
        break;
      case "send-open": {
        const contact = contactOf(entryId, contactId);
        this._openDialog({
          kind: "send",
          entryId,
          contactId,
          name: contact.name,
          phone: contact.phone,
        });
        break;
      }
      case "edit-open": {
        const contact = contactOf(entryId, contactId);
        this._openDialog({
          kind: "edit",
          entryId,
          contactId,
          name: contact.name,
          phone: contact.phone,
        });
        break;
      }
      case "delete-open": {
        const contact = contactOf(entryId, contactId);
        this._openDialog({ kind: "delete", entryId, contactId, name: contact.name });
        break;
      }
      case "send-confirm":
        this._sendMessage();
        break;
      case "edit-confirm":
        this._saveContact();
        break;
      case "delete-confirm":
        this._deleteContact();
        break;
      case "dialog-close":
        this._closeDialog();
        break;
      case "snack-close":
        this._snack = null;
        this._render();
        break;
      default:
        break;
    }
  }

  // -------------------------------------------------------------- styles

  _styles() {
    return `
      <style>
        :host {
          /* TextNow purple stays fixed: it is only ever used behind white
             text, so it reads the same in light and dark themes. */
          --brand: #6a2eaa;
          --brand-dark: #56238c;
          --ok: #2e7d4f;
          --warn: #9a6200;
          --bad: #c02a1d;
          --idle: #5c6370;

          --surface: var(--card-background-color, #fff);
          --page: var(--primary-background-color, #f2f3f6);
          --text: var(--primary-text-color, #16161a);
          --muted: var(--secondary-text-color, #5f6368);
          --line: var(--divider-color, rgba(0, 0, 0, 0.12));
          --radius: var(--ha-card-border-radius, 14px);
          --shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0, 0, 0, 0.08));

          display: block;
          height: 100%;
          background: var(--page);
          color: var(--text);
          font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
          font-size: 14px;
          line-height: 1.5;
          -webkit-font-smoothing: antialiased;
        }

        *, *::before, *::after { box-sizing: border-box; }
        svg { fill: currentColor; display: block; flex: 0 0 auto; }

        .app { display: flex; flex-direction: column; height: 100%; }

        /* ---------------------------------------------------------- bar */
        .bar {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 10px 20px;
          min-height: 64px;
          /* Deliberately not --app-header-background-color: in the default
             theme that is a saturated blue, and the secondary text and the
             inactive tabs below are theme greys, which is unreadable on it. */
          background: var(--surface);
          color: var(--text);
          border-bottom: 1px solid var(--line);
          position: relative;
          z-index: 2;
        }
        .logo {
          position: relative;
          width: 34px;
          height: 34px;
          border-radius: 9px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          background: linear-gradient(135deg, #8b3cbf, var(--brand));
          flex: 0 0 auto;
        }
        .logo img {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          object-fit: contain;
          border-radius: 9px;
        }
        .titles { flex: 1; min-width: 0; }
        .titles h1 {
          margin: 0;
          font-size: 20px;
          font-weight: 500;
          letter-spacing: 0.1px;
        }
        .titles p {
          margin: 0;
          font-size: 12.5px;
          color: var(--muted);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .app:not(.narrow) .menu-btn { display: none; }
        .narrow .bar { padding: 8px 12px; gap: 10px; }

        .pill {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          border: 1px solid var(--line);
          background: var(--surface);
          color: var(--text);
          border-radius: 999px;
          padding: 6px 12px 6px 10px;
          font: inherit;
          font-size: 12.5px;
          font-weight: 500;
          cursor: pointer;
        }
        .pill:hover { border-color: currentColor; }
        .dot {
          display: inline-block;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--idle);
          vertical-align: middle;
          margin-left: 4px;
        }
        .pill .dot { margin: 0; }
        .dot-ok { background: var(--ok); }
        .dot-warn { background: #d18b00; }
        .dot-bad { background: var(--bad); }
        .dot-idle { background: var(--idle); }
        .pill-ok .dot { background: var(--ok); }
        .pill-warn .dot { background: #d18b00; }
        .pill-bad .dot { background: var(--bad); }
        .pill-bad { border-color: var(--bad); }

        /* --------------------------------------------------------- tabs */
        .tabs {
          display: flex;
          gap: 4px;
          padding: 0 16px;
          background: var(--surface);
          border-bottom: 1px solid var(--line);
          position: relative;
          z-index: 1;
        }
        .tab {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          border: none;
          background: none;
          color: var(--muted);
          font: inherit;
          font-weight: 500;
          padding: 13px 14px 11px;
          cursor: pointer;
          border-bottom: 3px solid transparent;
          transition: color 0.15s, border-color 0.15s;
        }
        .tab:hover { color: var(--text); }
        .tab.active { color: var(--text); border-bottom-color: var(--brand); }
        .compact .tabs { padding: 0 4px; }
        .compact .tab { flex: 1; justify-content: center; padding: 13px 4px 10px; }
        .compact .tab svg { display: none; }

        /* ------------------------------------------------------ content */
        .content { flex: 1; overflow-y: auto; }
        .page {
          max-width: 860px;
          margin: 0 auto;
          padding: 20px 20px 48px;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .narrow .page { padding: 14px 12px 40px; gap: 12px; }

        .card {
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: var(--radius);
          box-shadow: var(--shadow);
          padding: 20px;
        }
        .narrow .card { padding: 16px; }
        .card h2 { margin: 0; font-size: 17px; font-weight: 500; }
        .card > p { margin: 10px 0 0; }
        .card-head {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 4px;
          flex-wrap: wrap;
        }
        .card-head > div { min-width: 0; flex: 1 1 auto; }
        .compact .card-head .btn { padding: 9px 12px; }
        .sub { color: var(--muted); font-size: 13px; margin: 3px 0 0; }
        .center { text-align: center; }
        .lede { color: var(--muted); margin-top: 8px; }
        .explain { margin: 12px 0 0; color: var(--muted); }
        .note {
          margin: 16px 0 0;
          padding: 12px 14px;
          border-radius: 10px;
          background: rgba(106, 46, 170, 0.08);
          border-left: 3px solid var(--brand);
          font-size: 13px;
        }

        .row { display: flex; align-items: center; }
        .row.gap { gap: 10px; margin-top: 18px; flex-wrap: wrap; }
        .row.end { justify-content: flex-end; }
        .row.wrap { flex-wrap: wrap; justify-content: center; }

        /* ------------------------------------------------------ buttons */
        .btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          border: 1px solid var(--line);
          background: var(--surface);
          color: var(--text);
          border-radius: 10px;
          padding: 9px 16px;
          font: inherit;
          font-size: 13.5px;
          font-weight: 500;
          cursor: pointer;
          text-decoration: none;
          transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
        }
        .btn:hover { background: rgba(127, 127, 127, 0.1); }
        .btn:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
        .btn[disabled] { opacity: 0.5; cursor: not-allowed; }
        .btn.primary {
          background: var(--brand);
          border-color: var(--brand);
          color: #fff;
        }
        .btn.primary:hover { background: var(--brand-dark); border-color: var(--brand-dark); }
        .btn.danger { background: var(--bad); border-color: var(--bad); color: #fff; }
        .btn.danger:hover { filter: brightness(0.92); }
        .btn.quiet { border-color: transparent; background: transparent; }
        .btn.sm { padding: 7px 12px; font-size: 13px; }
        .btn.lg { padding: 12px 22px; font-size: 15px; }

        .icon-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 38px;
          height: 38px;
          border: none;
          border-radius: 50%;
          background: transparent;
          color: var(--muted);
          cursor: pointer;
          transition: background 0.15s, color 0.15s;
        }
        .icon-btn:hover { background: rgba(127, 127, 127, 0.14); color: var(--text); }
        .icon-btn:focus-visible { outline: 2px solid var(--brand); outline-offset: 1px; }
        .icon-btn.danger:hover { background: rgba(192, 42, 29, 0.14); color: var(--bad); }
        .icon-btn.tiny { width: 30px; height: 30px; }

        /* ------------------------------------------------------ notices */
        .strip {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px 16px;
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: var(--radius);
          box-shadow: var(--shadow);
        }
        .strip { flex-wrap: wrap; }
        .strip-text { color: var(--muted); font-size: 13px; flex: 1 1 auto; }
        .compact .strip-text { flex-basis: 100%; order: 3; }
        .compact .strip .btn { margin-left: auto; }
        .badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          border-radius: 999px;
          padding: 4px 11px 4px 8px;
          font-size: 12.5px;
          font-weight: 600;
          color: #fff;
          background: var(--idle);
        }
        .badge.ok { background: var(--ok); }

        .notice { display: flex; gap: 16px; align-items: flex-start; }
        .notice-icon {
          width: 44px;
          height: 44px;
          border-radius: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          background: var(--idle);
          flex: 0 0 auto;
        }
        .notice-body { min-width: 0; }
        .notice-body p { margin: 8px 0 0; color: var(--muted); }
        .tone-ok .notice-icon, .tone-ok .status-icon { background: var(--ok); }
        .tone-warn .notice-icon, .tone-warn .status-icon { background: var(--warn); }
        .tone-bad .notice-icon, .tone-bad .status-icon { background: var(--bad); }
        .tone-idle .notice-icon, .tone-idle .status-icon { background: var(--idle); }
        .notice.tone-bad { border-left: 4px solid var(--bad); }
        .notice.tone-warn { border-left: 4px solid var(--warn); }

        /* ------------------------------------------------------ contacts */
        .list { list-style: none; margin: 14px 0 0; padding: 0; }
        .item {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 10px 12px;
          border-radius: 12px;
          transition: background 0.15s;
        }
        .item + .item { margin-top: 2px; }
        .item:hover { background: rgba(127, 127, 127, 0.08); }
        .avatar {
          width: 42px;
          height: 42px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          font-weight: 600;
          font-size: 15px;
          flex: 0 0 auto;
        }
        .item-text { flex: 1; min-width: 0; }
        .item-name {
          font-weight: 500;
          font-size: 15px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .item-sub { display: flex; align-items: center; gap: 2px; color: var(--muted); }
        .phone {
          font-variant-numeric: tabular-nums;
          font-size: 13px;
          letter-spacing: 0.2px;
        }
        .item-actions { display: flex; align-items: center; gap: 4px; }
        .compact .hide-narrow, .compact .hide-compact { display: none; }

        .empty {
          text-align: center;
          padding: 28px 16px 8px;
          color: var(--muted);
        }
        .empty svg { margin: 0 auto 10px; opacity: 0.45; }
        .empty p { margin: 0 0 4px; }
        .empty .btn { margin-top: 16px; }

        /* --------------------------------------------------------- form */
        .form {
          margin: 16px 0 4px;
          padding: 16px;
          border: 1px solid var(--line);
          border-radius: 12px;
          background: rgba(127, 127, 127, 0.05);
        }
        .fields { display: flex; gap: 14px; flex-wrap: wrap; }
        .fields .field { flex: 1 1 200px; }
        .field { display: block; }
        .field > span {
          display: block;
          font-size: 12.5px;
          font-weight: 600;
          color: var(--muted);
          margin-bottom: 6px;
          letter-spacing: 0.2px;
        }
        .field input, .field textarea {
          width: 100%;
          padding: 11px 13px;
          border: 1px solid var(--line);
          border-radius: 10px;
          background: var(--surface);
          color: var(--text);
          font: inherit;
          resize: vertical;
        }
        .field input:focus, .field textarea:focus {
          outline: none;
          border-color: var(--brand);
          box-shadow: 0 0 0 3px rgba(106, 46, 170, 0.18);
        }
        .field small { display: block; margin-top: 6px; color: var(--muted); font-size: 12px; }
        .field-error {
          margin: 12px 0 0;
          color: var(--bad);
          font-size: 13px;
          font-weight: 500;
        }

        /* -------------------------------------------------------- facts */
        .status-head { display: flex; align-items: center; gap: 16px; }
        .status-icon {
          width: 52px;
          height: 52px;
          border-radius: 14px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          flex: 0 0 auto;
        }
        .status-head h2 { font-size: 18px; }
        .facts {
          margin: 18px 0 0;
          padding: 0;
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
          gap: 1px;
          background: var(--line);
          border: 1px solid var(--line);
          border-radius: 12px;
          overflow: hidden;
        }
        .facts > div { background: var(--surface); padding: 12px 14px; }
        .facts dt { color: var(--muted); font-size: 12px; margin: 0 0 2px; }
        .facts dd { margin: 0; font-weight: 500; }
        .tech { margin-top: 14px; font-size: 13px; }
        .tech summary { cursor: pointer; color: var(--muted); }
        .tech code {
          display: block;
          margin-top: 8px;
          padding: 10px 12px;
          border-radius: 8px;
          background: rgba(127, 127, 127, 0.12);
          font-size: 12px;
          word-break: break-word;
        }
        .keepalive {
          display: grid;
          grid-template-columns: auto 1fr auto;
          align-items: start;
          gap: 12px;
          margin-top: 18px;
          padding: 14px;
          border: 1px solid var(--line);
          border-radius: 12px;
          background: rgba(127, 127, 127, 0.05);
        }
        .keepalive .ka-icon { color: var(--muted); padding-top: 2px; }
        .keepalive .ka-icon.ok { color: var(--ok); }
        .keepalive.off .ka-icon { color: var(--warn); }
        .ka-text { min-width: 0; }
        .ka-text strong { display: block; }
        .ka-text .sub { margin: 2px 0 0; }
        /* Narrow: the button drops under the text rather than pushing the
           icon onto a row of its own. */
        .compact .keepalive { grid-template-columns: auto 1fr; }
        .compact .keepalive .btn { grid-column: 2; justify-self: end; }

        .about { text-align: center; }
        .about .row { margin-top: 0; }
        .about .sub { margin-top: 14px; }

        /* -------------------------------------------------------- steps */
        .hero { text-align: center; padding: 36px 24px; }
        .hero-art {
          width: 76px;
          height: 76px;
          margin: 0 auto 18px;
          border-radius: 22px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          background: linear-gradient(135deg, #8b3cbf, var(--brand));
          box-shadow: 0 8px 20px rgba(106, 46, 170, 0.3);
        }
        .hero h2 { font-size: 22px; }
        .hero .lede { max-width: 52ch; margin: 10px auto 0; }
        .hero-actions {
          display: flex;
          gap: 12px;
          justify-content: center;
          flex-wrap: wrap;
          margin-top: 24px;
        }

        .steps { list-style: none; margin: 20px 0 0; padding: 0; text-align: left; }
        .steps li { display: flex; gap: 14px; padding: 9px 0; }
        .steps.compact { max-width: 46ch; margin: 22px auto 0; }
        .num {
          width: 26px;
          height: 26px;
          border-radius: 50%;
          background: var(--brand);
          color: #fff;
          font-size: 13px;
          font-weight: 600;
          display: flex;
          align-items: center;
          justify-content: center;
          flex: 0 0 auto;
        }
        .steps code, .card code {
          background: rgba(127, 127, 127, 0.16);
          border-radius: 5px;
          padding: 1px 5px;
          font-size: 12.5px;
        }
        /* The screenshots are wide and detailed, so they fill the card and
           scroll sideways on a phone rather than shrinking into something
           unreadable. */
        .shot { margin: 12px 0 2px; overflow-x: auto; }
        .shot img {
          display: block;
          width: 100%;
          min-width: 520px;
          border-radius: 10px;
          border: 1px solid var(--line);
          box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
        }
        .shot figcaption {
          margin-top: 6px;
          font-size: 12px;
          color: var(--muted);
        }

        /* ------------------------------------------------------ dialogs */
        .scrim {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.45);
          z-index: 10;
          animation: fade 0.15s ease-out;
        }
        .dialog {
          position: fixed;
          z-index: 11;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          width: min(440px, calc(100vw - 32px));
          max-height: calc(100vh - 64px);
          overflow: auto;
          background: var(--surface);
          color: var(--text);
          border-radius: 16px;
          box-shadow: 0 16px 48px rgba(0, 0, 0, 0.3);
          animation: pop 0.16s ease-out;
        }
        .dialog-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          padding: 18px 12px 12px 22px;
        }
        .dialog-head h2 { margin: 0; font-size: 18px; font-weight: 500; }
        .dialog-body { padding: 0 22px 4px; }
        .dialog-body p { margin: 0 0 14px; color: var(--muted); }
        .dialog-foot {
          display: flex;
          justify-content: flex-end;
          gap: 10px;
          padding: 16px 22px 20px;
        }

        /* -------------------------------------------------------- snack */
        .snack {
          position: fixed;
          z-index: 12;
          left: 50%;
          bottom: 24px;
          transform: translateX(-50%);
          display: flex;
          align-items: center;
          gap: 10px;
          max-width: min(520px, calc(100vw - 32px));
          padding: 11px 10px 11px 16px;
          border-radius: 12px;
          background: #2b2b30;
          color: #fff;
          box-shadow: 0 8px 28px rgba(0, 0, 0, 0.35);
          animation: rise 0.18s ease-out;
        }
        .snack .icon-btn { color: rgba(255, 255, 255, 0.7); }
        .snack .icon-btn:hover { background: rgba(255, 255, 255, 0.15); color: #fff; }
        .snack.tone-ok svg:first-child { color: #6ee7a0; }
        .snack.tone-warn svg:first-child { color: #ffc766; }
        .snack.tone-bad svg:first-child { color: #ff9b91; }

        /* ---------------------------------------------------- skeletons */
        .sk-row { display: flex; align-items: center; gap: 14px; padding: 10px 0; }
        .sk { background: rgba(127, 127, 127, 0.18); border-radius: 8px; animation: pulse 1.4s infinite; }
        .sk-avatar { width: 42px; height: 42px; border-radius: 50%; }
        .sk-lines { flex: 1; }
        .sk-line { height: 12px; margin-bottom: 8px; width: 45%; }
        .sk-line.short { width: 25%; margin-bottom: 0; }

        @keyframes pulse { 50% { opacity: 0.45; } }
        @keyframes fade { from { opacity: 0; } }
        @keyframes pop { from { opacity: 0; transform: translate(-50%, -46%) scale(0.97); } }
        @keyframes rise { from { opacity: 0; transform: translate(-50%, 12px); } }

        @media (prefers-reduced-motion: reduce) {
          * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
        }
      </style>
    `;
  }
}

customElements.define("textnow-panel", TextNowPanel);
