# Mecatech Pointage v2.2.4

## Attendance log correction
- Editing a record now changes date/time only; the original IN/OUT action is preserved.
- Removed the editable IN/OUT selector.
- Removed the consecutive-action validation error from timestamp correction.
- Direct deletion remains available.

## Application color
- Removed the hard-coded primary-color override from the global stylesheet.
- The configured `primary_color` now drives the CSS variable used by the application.
- Added synchronized color picker/text input handling before settings save.

## ESP32
- ESP-facing code remains unchanged and is protected by the existing contract test.
