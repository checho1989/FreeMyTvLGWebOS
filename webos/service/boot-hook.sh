#!/bin/sh
# Free My TV boot hook. webos/install.py --home copies it to /var/lib/webosbrew/init.d/60-freemytv,
# and Homebrew Channel runs it as root on every cold boot.
#
# It starts the service, which puts Free My TV back in front whenever the system opens the stock
# home by id (see watchHome in service.js). If Free My TV has been removed, it gives the Home key
# back to the stock home and deletes itself; otherwise Home would open nothing.
APP_ID=io.freemytv

if [ ! -d "/media/developer/apps/usr/palm/applications/$APP_ID" ]; then
  luna-send -n 1 luna://com.webos.applicationManager/setDefaultApp '{"category":"home","appId":"com.webos.app.home"}' </dev/null >/dev/null 2>&1
  rm -f "$0"
  exit 0
fi

luna-send -n 1 "luna://$APP_ID.service/start" '{}' </dev/null >/dev/null 2>&1 &
exit 0
