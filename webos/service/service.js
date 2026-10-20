// Free My TV's webOS background service: lists installed apps for the home screen, keeps Free My TV
// as the TV's Home app, and switches back to LG's home. It runs elevated (Homebrew Channel's
// elevate-service), started by boot-hook.sh at every cold boot, and stays running the rest of the
// time.
//
// Without Developer Mode (installed as root, over Homebrew Channel's SSH instead), the page's own
// Luna calls only reach the "public" bus, which denies applicationManager/listLaunchPoints ("Denied
// method call" for category "/") — so the home screen's apps list and All Apps come up empty. This
// service, elevated, makes that call instead; web/tv.js tries it first and falls back to calling
// listLaunchPoints from the page directly, which still works for an install under real Developer Mode.
//
// The Home key opens SAM's (the app manager's) default "home" app (settingsservice's
// defaultApps.home), which webos/install.py --home points at Free My TV. Two system paths still
// launch the stock home by id regardless of that setting: bootd at power-on, and SAM's last-input
// fallback when an app closes. This service watches for that and switches back to Free My TV.
// Same technique as guntiss/webos-galaxy-launcher (MIT).
var Service = require('webos-service');
var fs = require('fs');
var path = require('path');

var service = new Service('io.freemytv.service');
var LOG = '/tmp/freemytv-service.log';
var APP_ID = 'io.freemytv';
var STOCK_HOME = 'com.webos.app.home';
var LIVE_TV = 'com.webos.app.livetv';
var MAX_REDIRECTS = 3;          // per REDIRECT_WINDOW_MS, so a broken build can't loop forever
var REDIRECT_WINDOW_MS = 30000;
var ICON_MIME = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml'};

function log(msg) {
  try { fs.appendFileSync(LOG, new Date().toISOString() + ' ' + msg + '\n'); } catch (e) { /* ignore */ }
}

// Other apps' icon files live in directories the page can't read; this service, elevated, can. Embedded
// as a data URL so web/tv.js needs no second round trip per icon.
function iconDataUrl(file) {
  var mime = file && ICON_MIME[path.extname(file).toLowerCase()];
  if (!mime) return '';
  try {
    return 'data:' + mime + ';base64,' + fs.readFileSync(file).toString('base64');
  } catch (e) {
    return '';
  }
}

// webos-service exits after 5 s idle; an open activity, plus a timer, hold Node's event loop open.
service.activityManager.create('keepAlive', function () {});
setInterval(function () {}, 3600 * 1000);

var defaultHome = ''; // SAM's current default home app, '' until known
var redirectTimes = [];

function watchDefaultHome() {
  var sub = service.subscribe('luna://com.webos.settingsservice/getSystemSettings',
    {category: 'general', keys: ['defaultApps'], subscribe: true});
  sub.on('response', function (res) {
    var apps = (res.payload.settings || {}).defaultApps;
    if (apps && apps.home) defaultHome = apps.home;
  });
  sub.on('cancel', function () { setTimeout(watchDefaultHome, 2000); });
}

var lastAppId = '';       // for the log only, so a failed attempt's history can be read back afterward
var recentlyLiveTv = false; // Live TV was foreground, and nothing else "real" has shown since
// Transitional states SAM passes through on its way out of Live TV (confirmed in the log: Live TV ->
// com.webos.app.discovery -> '' -> com.webos.app.home, or straight to the next real app) — recentlyLiveTv
// survives these, so the video-plane cleanup below still fires once a real app lands, however it got there.
var TRANSITIONAL = {'': true, 'com.webos.app.discovery': true};
TRANSITIONAL[STOCK_HOME] = true;

function watchHome() {
  var sub = service.subscribe('luna://com.webos.applicationManager/getForegroundAppInfo', {subscribe: true});
  sub.on('response', function (res) {
    var appId = (res.payload || {}).appId;
    if (appId !== lastAppId) {
      log('foreground: ' + lastAppId + ' -> ' + appId);
      lastAppId = appId;
    }

    if (appId === LIVE_TV) {
      recentlyLiveTv = true;
    } else if (recentlyLiveTv && !TRANSITIONAL[appId]) {
      // Leaving Live TV doesn't reliably release its video plane for the app that replaces it, the way
      // it does for LG's own home (the new app does become foreground either way; sometimes the video
      // plane is still the one on screen regardless of which path got it there). Closing it once a real
      // app has landed clears it either way.
      recentlyLiveTv = false;
      service.call('luna://com.webos.applicationManager/closeByAppId', {id: LIVE_TV}, function (c) {
        log('closeByAppId ' + LIVE_TV + ' (left for ' + appId + '): ' + JSON.stringify(c.payload));
      });
    }

    if (appId !== STOCK_HOME || defaultHome === STOCK_HOME) return;
    var now = Date.now();
    redirectTimes = redirectTimes.filter(function (t) { return now - t < REDIRECT_WINDOW_MS; });
    if (redirectTimes.length >= MAX_REDIRECTS) {
      log('stock home in front, but ' + MAX_REDIRECTS + ' redirects in ' + (REDIRECT_WINDOW_MS / 1000) + 's; leaving it');
      return;
    }
    redirectTimes.push(now);
    service.call('luna://com.webos.applicationManager/launch', {id: APP_ID}, function (r) {
      log('stock home in front, launched ' + APP_ID + ': ' + JSON.stringify(r.payload));
    });
  });
  sub.on('cancel', function (res) {
    log('foreground subscription dropped: ' + JSON.stringify(res.payload) + '; resubscribing');
    setTimeout(watchHome, 2000);
  });
}

watchDefaultHome();
watchHome();
log('service started');

// Toggles between Free My TV and LG's home: makes the other one SAM's default and opens it. Bind a
// remote button to it with LG Input Mapper (an "exec" action running
// `luna-send -n 1 luna://io.freemytv.service/switchHome '{}' </dev/null`), so it works from any app.
// Switch through this, not setDefaultApp plus a launch of your own: the service needs to know about
// the new default before the stock home comes to front, or it treats it as a system launch and
// brings Free My TV back in front of it.
service.register('switchHome', function (message) {
  service.call('luna://com.webos.settingsservice/getSystemSettings', {category: 'general', keys: ['defaultApps']}, function (res) {
    var apps = (res.payload.settings || {}).defaultApps || {};
    var target = apps.home === STOCK_HOME ? APP_ID : STOCK_HOME;
    service.call('luna://com.webos.applicationManager/setDefaultApp', {category: 'home', appId: target}, function (r) {
      if (!r.payload.returnValue) {
        log('switchHome: setDefaultApp ' + target + ' failed: ' + JSON.stringify(r.payload));
        message.respond({returnValue: false, errorText: r.payload.errorText || 'setDefaultApp failed'});
        return;
      }
      defaultHome = target; // before the launch, so watchHome leaves the stock home alone
      service.call('luna://com.webos.applicationManager/launch', {id: target}, function (l) {
        log('switchHome (' + message.sender + '): home is now ' + target + ', launch: ' + JSON.stringify(l.payload));
      });
      message.respond({returnValue: true, home: target});
    });
  });
});

// Called by boot-hook.sh (and webos/install.py --home right after install) to start the service.
service.register('start', function (message) {
  message.respond({returnValue: true});
});

// The installed apps, the same list LG's own launcher reads (web/tv.js filters and renders them).
service.register('listApps', function (message) {
  service.call('luna://com.webos.applicationManager/listLaunchPoints', {}, function (res) {
    var p = res.payload || {};
    if (!p.launchPoints) {
      log('listApps: listLaunchPoints failed: ' + JSON.stringify(p));
      message.respond({returnValue: false, errorText: p.errorText || 'listLaunchPoints failed'});
      return;
    }
    var apps = p.launchPoints.map(function (lp) {
      return {id: lp.id, title: lp.title || lp.id, icon: iconDataUrl(lp.largeIcon || lp.icon || ''), color: lp.bgColor || lp.iconColor || ''};
    });
    message.respond({returnValue: true, apps: apps});
  });
});
