# Changelog

Notable changes to CatSwitch.

## 0.1.1

### Security
- Added CSRF protection to the local API (Host / Origin / Sec-Fetch-Site checks)
- Changed destructive list and update endpoints from GET to POST
- Fixed path traversal in remote exclusion-list downloads
- Limited remote list downloads to HTTPS and a 10 MB size cap
- Fixed XSS from unescaped remote list names in the UI
- Fixed path containment checks to resolve symlinks and ignore Windows path casing
- Replaced the tkinter file dialog with the native pywebview dialog
- Moved update helper files into a private temp folder

### Fixed
- Require Edge WebView2 at startup (Download / Exit dialog if missing; no MSHTML fallback)
- Ignore window-title churn once the focused process is already identified as a game
- Added Help, Changelog, and Issues links on the Info tab
- Fixed a potential issue with applying Twitch category

## 0.1.0

- Initial public release
