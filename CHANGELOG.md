# Changelog

Notable changes to CatSwitch.

## Unreleased

### Security
- Added CSRF protection to the local API (Host / Origin / Sec-Fetch-Site checks)
- Changed destructive list and update endpoints from GET to POST
- Fixed path traversal in remote exclusion-list downloads
- Limited remote list downloads to HTTPS and a 10 MB size cap
- Fixed XSS from unescaped remote list names in the UI
- Fixed path containment checks to resolve symlinks and ignore Windows path casing

## 0.1.0

- Initial public release
