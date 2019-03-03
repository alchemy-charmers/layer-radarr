from charms.reactive import (
    when_all,
    when_not,
    set_state,
    hook
)

from charmhelpers.core import host
from charmhelpers.core import hookenv
from pathlib import Path
from zipfile import ZipFile
from lib_radarr import RadarrHelper

import os
import time
import socket

radarr = RadarrHelper()


@hook('upgrade-charm')
def hanlde_upgrade():
    if not radarr.kv.get('mono-source'):
        radarr.install_deps()


@when_all('layer-service-account.configured')
@when_not('radarr.installed')
def install_radarr():
    hookenv.status_set('maintenance', 'Installing Radarr')
    radarr.install_radarr()
    hookenv.status_set('maintenance', 'Installed')
    set_state('radarr.installed')


@when_all('radarr.installed',
          'layer-service-account.configured',
          'layer-hostname.installed')
@when_not('radarr.configured')
def setup_config():
    hookenv.status_set('maintenance', 'Configuring Radarr')
    backups = './backups'
    if radarr.charm_config['restore-config']:
        try:
            os.mkdir(backups)
        except OSError as e:
            if e.errno == 17:
                pass
        backupFile = hookenv.resource_get('radarrconfig')
        if backupFile:
            with ZipFile(backupFile, 'r') as inFile:
                inFile.extractall(radarr.config_dir)
            hookenv.log(
                "Restoring config, indexers are disabled enable with action when configuration has been checked", 'INFO'
            )
            # Turn off indexers
            radarr.set_indexers(False)
        else:
            hookenv.log("Add radarrconfig resource, see juju attach or disable restore-config", 'WARN')
            hookenv.status_set('blocked', 'waiting for radarrconfig resource')
            return
    else:
        host.service_start(radarr.service_name)
        configFile = Path(radarr.config_file)
        while not configFile.is_file():
            time.sleep(1)
    radarr.modify_config(port=radarr.charm_config['port'], urlbase='None')
    hookenv.open_port(radarr.charm_config['port'], 'TCP')
    host.service_start(radarr.service_name)
    hookenv.status_set('active', 'Radarr is ready')
    set_state('radarr.configured')


@when_not('usenet-downloader.configured')
@when_all('usenet-downloader.triggered', 'usenet-downloader.available', 'radarr.configured')
def configure_downloader(usenetdownloader, *args):
    hookenv.log(
        "Setting up sabnzbd relation requires editing the database and may not work",
        "WARNING")
    radarr.setup_sabnzbd(port=usenetdownloader.port(),
                         apikey=usenetdownloader.apikey(),
                         hostname=usenetdownloader.hostname())
    usenetdownloader.configured()


@when_not('plex-info.configured')
@when_all('plex-info.triggered', 'plex-info.available', 'radarr.configured')
def configure_plex(plexinfo, *args):
    hookenv.log("Setting up plex relation requires editing the database and may not work", "WARNING")
    radarr.setup_plex(hostname=plexinfo.hostname(), port=plexinfo.port(),
                      user=plexinfo.user(), passwd=plexinfo.passwd())
    plexinfo.configured()


@when_all('reverseproxy.triggered', 'reverseproxy.ready')
@when_not('reverseproxy.configured', 'reverseproxy.departed')
def configure_reverseproxy(reverseproxy, *args):
    hookenv.log("Setting up reverseproxy", "INFO")
    proxy_info = {'urlbase': radarr.charm_config['proxy-url'],
                  'subdomain': radarr.charm_config['proxy-domain'],
                  'group_id': radarr.charm_config['proxy-group'],
                  'external_port': radarr.charm_config['proxy-port'],
                  'internal_host': socket.getfqdn(),
                  'internal_port': radarr.charm_config['port']
                  }
    reverseproxy.configure(proxy_info)
    radarr.modify_config(urlbase=radarr.charm_config['proxy-url'])
    host.service_restart(radarr.service_name)


@when_all('reverseproxy.triggered', 'reverseproxy.departed')
def remove_urlbase(reverseproxy, *args):
    hookenv.log("Removing reverseproxy configuration", "INFO")
    radarr.modify_config(urlbase='None')
    host.service_restart(radarr.service_name)
