# webos-debloat

Vendored from [lucataco's gist](https://gist.github.com/lucataco/7c303b443934008a9031a55cfca552ec) (MIT), unchanged.
Run through `webos/install.py --debloat*` (see the main README's *Debloat* section) rather than by hand, unless
you're doing something this project doesn't wrap — `--list`, `--status`, or a single `--id`.

One shell script that makes a rooted LG webOS TV lighter and quieter:

- **hides** bloat tiles and background apps from the launcher
- **stops preloading** apps the TV keeps in RAM whether or not you open them
- **turns off** home-screen promotions, promo videos, sports alerts,
  content recommendations and Live Plus (ACR)

Nothing is deleted and the root filesystem is never touched. It only edits
LG's own app block list, the preload manager's policy and a few system
settings. So every change can be undone, and firmware updates install as
they would on a stock TV.

> **Status: tested on one TV, not everywhere.** It was written on a 2026
> LG OLED running webOS 26 (firmware 11.2, US region). On other models and
> versions it should work in principle: app IDs that aren't installed and
> settings keys that don't exist are skipped. But it hasn't been tried there.
> Start with `--plan` and `--dry-run`.

## Categories

`--apply` hides the default categories. Pick others with `--only a,b,c`, or
hide single apps with `--id <app-id>`.

| category | what | default |
|---|---|---|
| `ad` | ACR, ad overlays, "food delivery" overlays, video ads | yes |
| `sdk` | example apps that ship in the firmware | yes |
| `demo` | store demo, factory and diagnostics apps | yes |
| `remote` | LG remote-support service | yes |
| `promo` | LG Channels, Sports, Music, Photo & Video, user guide, weather | no |
| `visible` | launcher tiles: LG Channels, Home Hub, Premium, Multi View settings, … | no |
| `extras` | AI/voice assistant, membership, family care, customer support, Remote PC, … | no |
| `all` | all of the above | no |

`extras` hides the voice assistant and LG account pages, so skip it if you
use them. Some apps are never hidden, whatever you ask for (`PROTECTED_IDS`
in the script): Home, Settings, Live TV, inputs, the browser, first-run
setup, Homebrew Channel and anything else whose absence is known to break
the TV's own UI.

## Things learned along the way (from the original author)

- **Hiding is mostly cosmetic.** It removes tiles from the app list but
  doesn't stop processes or free memory.
- **The memory goes to preloading.** The preload manager keeps some apps
  resident before anyone opens them (`--preload-off` is the step that
  actually frees RAM). It leaves Home, Live TV and the HDMI inputs
  preloaded — that's what keeps the Home button and input switching fast.
- **"Off" is usually suspend.** With the default power settings, turning
  the TV off suspends it; boot hooks run only after a real reboot. Every
  change here is stored in `/var`, so that doesn't matter for this script.

## Security note

Homebrew Channel's telnet is an unauthenticated root shell open to your
whole network. Once you're set up, enable SSH with a key in Homebrew
Channel's settings and turn telnet off.

## License

MIT. Not affiliated with LG. Rooting your TV may void its warranty; use at your own risk.
