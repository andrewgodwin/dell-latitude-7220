# Touch Mode plasmoid

KDE Plasma 6 system tray applet to view and switch the touchscreen mode
(Finger / Glove / Water). Needs `python3` and read/write access to the
touch controller's `/dev/hidrawN` node.

## Install

```sh
kpackagetool6 -t Plasma/Applet -i touch-mode/plasmoid
```

To update after changes, use `-u` instead of `-i`. To uninstall:
`kpackagetool6 -t Plasma/Applet -r org.aeracode.latitude7220.touchmode`.

Then right-click the system tray arrow → **Configure System Tray… →
Entries**, and set **Touch Mode** to "Always shown". If it isn't listed,
restart Plasma with `systemctl --user restart plasma-plasmashell`.
