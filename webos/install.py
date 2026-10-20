#!/usr/bin/env python3
"""Installs Free My TV on an LG TV, over your Wi-Fi: in Developer Mode, or as root with the Homebrew Channel.

    python3 webos/install.py 192.168.1.50              # Developer Mode: install or update, then open it
    python3 webos/install.py 192.168.1.50 --uninstall  # Developer Mode: remove it
    python3 webos/install.py 192.168.1.50 --root              # Homebrew Channel (rooted TV): install, then open it
    python3 webos/install.py 192.168.1.50 --root --uninstall  # Homebrew Channel: remove it
    python3 webos/install.py 192.168.1.50 --root --home        # also make Free My TV the TV's Home
    python3 webos/install.py 192.168.1.50 --root --switch-home  # toggle Home between Free My TV and LG's, now
    python3 webos/install.py 192.168.1.50 --root --home --uninstall  # remove it and restore LG's Home

Developer Mode (default): install "Developer Mode" from the LG Content Store, sign in with a free LG developer
account (webostv.developer.lge.com), turn on Dev Mode Status (the TV restarts), then turn on Key Server. The app
shows the TV's IP address and a passphrase. The first time, this downloads the TV's key from its Key Server and
asks for that passphrase (type it here; it is not stored). The unlocked key is kept in ~/.ssh/freemytv_webos_<IP>,
so updates need neither.

--root (a TV rooted with the webOS Homebrew Channel, e.g. via RootMyTV): no LG account, no 40-day limit. On the TV,
open Homebrew Channel and turn on SSH in its settings. The first time, this generates a local key
(~/.ssh/freemytv_webos_root_<IP>) and installs it on the TV over SSH (port 22, user root): type the TV's root
password when asked (the Homebrew Channel default is "alpine" until a key is installed, after which only the key
works). Later runs reuse that key.

--home (needs --root): makes Free My TV the Home key's app, the way Free My TV already is on Android TV. A
service (webos/service/, elevated through Homebrew Channel) keeps it there and switches back to LG's home when
the TV asks for it by name (at power-on, or when an app closes with nothing else to show), the same way the
Android Watchdog does, with the same kind of limit (3 redirects per 30 s) so a broken build can't loop. Three
ways back to LG's home, each independent of the others:
  - `--switch-home` toggles it from the computer, right now, without touching the install.
  - A remote button, through LG Input Mapper (github.com/anned20/lginputmapper): bind one to an "exec" action
    running `luna-send -n 1 luna://io.freemytv.service/switchHome '{}' </dev/null`.
  - `--uninstall` (with `--home` or without, it's harmless either way) always restores LG's home first, over SSH,
    before removing the app — so even if the Home key, the app and the remote button are all unusable, this still
    gets you back.
If Free My TV is ever removed another way (not through this script) while it's still the Home app, the Home key
opens nothing until the next reboot, when the boot hook notices, restores LG's home and removes itself.

Either way the app is copied over SSH and installed with the TV's own installer (com.webos.appInstallService), the
way LG's tools do it. Install flow based on FreeMyTvWebOS by danielthejoker18 (MIT); the Home-mode service follows
the same technique as guntiss/webos-galaxy-launcher (MIT). Needs Python 3 and OpenSSH (ssh, ssh-keygen).
"""
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IPK = os.path.join(ROOT, 'FreeMyTV-webos.ipk')
with open(os.path.join(ROOT, 'webos', 'appinfo.json'), encoding='utf-8') as f:
    APP_ID = json.load(f)['id']
SERVICE_ID = APP_ID + '.service'
STOCK_HOME = 'com.webos.app.home'
ELEVATE = '/media/developer/apps/usr/palm/services/org.webosbrew.hbchannel.service/elevate-service'
BOOT_HOOK = '/var/lib/webosbrew/init.d/60-freemytv'
DEVMODE_TEMP = '/media/developer/temp/freemytv.ipk'
ROOT_TEMP = '/tmp/freemytv.ipk'
SSH_BASE_OPTS = ['-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=' + os.devnull, '-o', 'LogLevel=ERROR',
                 '-o', 'HostKeyAlgorithms=+ssh-rsa', '-o', 'PubkeyAcceptedKeyTypes=+ssh-rsa']


def key_path(ip, root):
    name = ('freemytv_webos_root_' if root else 'freemytv_webos_') + ip.replace('.', '_')
    return os.path.join(os.path.expanduser('~'), '.ssh', name)


def fetch_devmode_key(ip):
    """The TV's SSH key from its Key Server, unlocked with the passphrase the TV shows."""
    path = key_path(ip, root=False)
    if os.path.exists(path):
        return path
    url = 'http://%s:9991/webos_rsa' % ip
    print('Getting the TV\'s key from %s ...' % url)
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            data = r.read()
    except Exception as e:
        sys.exit('Couldn\'t reach the Key Server (%s). In the TV\'s Developer Mode app, turn on Key Server.' % e)
    passphrase = getpass.getpass('Passphrase shown in Developer Mode on the TV: ').strip()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(data)
    tmp.close()
    os.chmod(tmp.name, 0o600)
    unlock = subprocess.run(['ssh-keygen', '-p', '-P', passphrase, '-N', '', '-f', tmp.name], capture_output=True, text=True)
    if unlock.returncode != 0:
        os.unlink(tmp.name)
        sys.exit('That passphrase didn\'t unlock the key. Check it on the TV (Developer Mode) and try again.')
    shutil.move(tmp.name, path)
    os.chmod(path, 0o600)
    return path


def provision_root_key(ip):
    """A local key for root@ip:22 (Homebrew Channel's SSH), installed on the TV's authorized_keys the first time."""
    path = key_path(ip, root=True)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(['ssh-keygen', '-t', 'ed25519', '-N', '', '-f', path, '-C', 'freemytv'], capture_output=True, check=True)
    test = subprocess.run(['ssh'] + SSH_BASE_OPTS + ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-p', '22',
                           '-i', path, 'root@' + ip, 'true'], capture_output=True)
    if test.returncode == 0:
        return path
    with open(path + '.pub', encoding='utf-8') as f:
        pubkey = f.read().strip()
    print('Installing the key on the TV: type its root password when asked (Homebrew Channel default: alpine,')
    print('until a key is installed; SSH must be turned on in Homebrew Channel\'s settings first).')
    install = subprocess.run(['ssh'] + SSH_BASE_OPTS +
                              ['-o', 'PreferredAuthentications=password,keyboard-interactive', '-p', '22', 'root@' + ip,
                               "mkdir -p /home/root/.ssh && chmod 700 /home/root/.ssh && echo '%s' >> "
                               "/home/root/.ssh/authorized_keys && chmod 600 /home/root/.ssh/authorized_keys" % pubkey])
    if install.returncode != 0:
        sys.exit('Couldn\'t install the key on the TV. Check the password and that SSH is on in Homebrew Channel, then try again.')
    return path


def ssh(ip, key, command, stdin=None, tty=False, user='prisoner', port=9922):
    args = ['ssh'] + (['-tt'] if tty else []) + SSH_BASE_OPTS + ['-p', str(port), '-i', key, '%s@%s' % (user, ip), command]
    return subprocess.run(args, stdin=stdin, capture_output=True, text=stdin is None)


def luna(ip, key, uri, payload, replies=1, wait=20, user='prisoner', port=9922, cmd='luna-send-pub'):
    # luna-send(-pub) prints nothing without a terminal (-tt), and the installer streams several replies.
    # Older webOS ships BusyBox before 1.30, whose timeout only takes -t SECS.
    # Some (webOS 6) refuse the terminal; there -i streams the replies without one, until the timeout.
    timeout = "if timeout -t 1 true 2>/dev/null; then T='timeout -t %d'; else T='timeout %d'; fi; " % (wait, wait)
    message = "%s '%s'" % (uri, json.dumps(payload, separators=(',', ':')))
    out = ssh(ip, key, timeout + '$T %s -n %d %s' % (cmd, replies, message), tty=True, user=user, port=port).stdout or ''
    if not out.strip():
        out = ssh(ip, key, timeout + '$T %s -i %s </dev/null' % (cmd, message), user=user, port=port).stdout or ''
    return out


def root_shell(ip, key, script):
    """A short root shell script over SSH (not through luna-send-pub): elevate-service, setDefaultApp, the boot hook."""
    return ssh(ip, key, script, user='root', port=22)


def elevate_service(ip, key):
    """Elevates the bundled service through Homebrew Channel, so it can read the TV's app list (and, with
    --home, call setDefaultApp etc.). Reinstalling the app resets this, so it runs after every --root install."""
    out = root_shell(ip, key,
                      "if [ -x %s ]; then %s %s && echo ELEVATED; else echo NOELEVATE; fi" % (ELEVATE, ELEVATE, SERVICE_ID))
    ok = 'ELEVATED' in (out.stdout or '')
    if not ok:
        print('Note: Homebrew Channel\'s elevate-service wasn\'t found, so the apps shelf and All Apps will stay empty.')
    return ok


def enable_home(ip, key):
    """Makes Free My TV the Home key's app, and installs the boot hook for next boot. Call elevate_service first."""
    print('Making Free My TV the Home key\'s app ...')
    root_shell(ip, key, "luna-send -n 1 luna://com.webos.applicationManager/setDefaultApp '{\"category\":\"home\",\"appId\":\"%s\"}' "
                        "</dev/null >/dev/null" % APP_ID)
    out = root_shell(ip, key, "if [ -d /var/lib/webosbrew/init.d ]; then "
                              "cp /media/developer/apps/usr/palm/services/%s/boot-hook.sh %s && chmod 755 %s && echo OK; fi"
                              % (SERVICE_ID, BOOT_HOOK, BOOT_HOOK))
    if 'OK' not in (out.stdout or ''):
        print('Homebrew Channel\'s init.d wasn\'t found: after a reboot, LG\'s home shows until Home is pressed once.')
    root_shell(ip, key, "luna-send -n 1 'luna://%s/start' '{}' </dev/null >/dev/null" % SERVICE_ID)


def disable_home(ip, key):
    """Gives the Home key back to LG's home and removes the boot hook, so Home never opens nothing."""
    root_shell(ip, key, "luna-send -n 1 luna://com.webos.applicationManager/setDefaultApp "
                        "'{\"category\":\"home\",\"appId\":\"%s\"}' </dev/null >/dev/null; rm -f %s" % (STOCK_HOME, BOOT_HOOK))


def switch_home(ip, key):
    """Toggles Home between Free My TV and LG's home, right now, without reinstalling or uninstalling anything."""
    out = luna(ip, key, 'luna://%s/switchHome' % SERVICE_ID, {}, replies=1, wait=10, user='root', port=22, cmd='luna-send')
    flat = out.replace(' ', '')
    if '"home":"%s"' % APP_ID in flat:
        print('Home is now Free My TV.')
    elif '"home":"%s"' % STOCK_HOME in flat:
        print('Home is now LG\'s home.')
    else:
        sys.exit('Couldn\'t switch: %s\nHas --home been run on this TV? (python3 webos/install.py %s --root --home)'
                  % (out.strip() or '(no answer)', ip))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args or not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', args[0]):
        sys.exit(__doc__)
    ip = args[0]
    if not shutil.which('ssh') or not shutil.which('ssh-keygen'):
        sys.exit('OpenSSH (ssh and ssh-keygen) is needed.')
    root = '--root' in sys.argv
    home = '--home' in sys.argv
    switch = '--switch-home' in sys.argv
    if (home or switch) and not root:
        sys.exit('--home and --switch-home need --root: Home mode needs a service elevated through Homebrew Channel.')
    user, port, temp = ('root', 22, ROOT_TEMP) if root else ('prisoner', 9922, DEVMODE_TEMP)
    key = provision_root_key(ip) if root else fetch_devmode_key(ip)

    if switch:
        switch_home(ip, key)
        return

    if '--uninstall' in sys.argv:
        if root:
            disable_home(ip, key)  # harmless if Home mode was never turned on
        out = luna(ip, key, 'luna://com.webos.appInstallService/dev/remove', {'id': APP_ID}, replies=3, wait=30,
                   user=user, port=port)
        print('Removed.' if '"returnValue":true' in out else 'The TV said: ' + out.strip())
        return

    if not os.path.exists(IPK):
        subprocess.run([sys.executable, os.path.join(ROOT, 'webos', 'build.py')], check=True)
    print('Copying the app to the TV ...')
    with open(IPK, 'rb') as f:
        copy = ssh(ip, key, 'mkdir -p %s && cat > %s' % (os.path.dirname(temp), temp), stdin=f, user=user, port=port)
    if copy.returncode != 0:
        err = copy.stderr.decode('utf-8', 'replace') if isinstance(copy.stderr, bytes) else copy.stderr
        hint = 'Is SSH still on in Homebrew Channel?' if root else 'Is Developer Mode still on?'
        sys.exit('Couldn\'t copy it: %s\n%s If the key changed, delete %s and try again.' % (err.strip(), hint, key))
    print('Installing ...')
    out = luna(ip, key, 'luna://com.webos.appInstallService/dev/install', {'id': APP_ID, 'ipkUrl': temp, 'subscribe': True},
               replies=30, wait=60, user=user, port=port)
    if '"state":"installed"' not in out:
        sys.exit('The TV didn\'t finish installing. It said:\n' + out.strip())
    ssh(ip, key, 'rm -f ' + temp, user=user, port=port)
    if root:
        elevate_service(ip, key)  # lets the service read the TV's app list, even without --home
    if home:
        enable_home(ip, key)
    luna(ip, key, 'luna://com.webos.applicationManager/launch', {'id': APP_ID}, user=user, port=port)
    print('Installed and open on the TV.')
    if home:
        print('Free My TV is now the Home key\'s app. To switch back to LG\'s home from the remote, set up LG Input')
        print('Mapper with an "exec" action running: luna-send -n 1 luna://%s/switchHome \'{}\' </dev/null' % SERVICE_ID)
    else:
        print('Tip: while Free My TV is open, hold a number key on the remote to open it with that key from anywhere.')
    if not root:
        print('Developer Mode lasts about 40 days: open the Developer Mode app now and then and press EXTEND.')


if __name__ == '__main__':
    main()
