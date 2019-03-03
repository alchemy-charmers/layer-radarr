#!/usr/bin/python3
from charmhelpers import fetch
from charmhelpers.core import hookenv
from charmhelpers.core import host
from charmhelpers.core import templating
from charmhelpers.core import unitdata
from github import Github

import fileinput
import sqlite3
import shutil
import json
import pwd
import grp
import os


class RadarrHelper:
    def __init__(self):
        self.charm_config = hookenv.config()
        self.user = self.charm_config['radarr-user']
        self.installdir = '/opt/Radarr'
        self.executable = '{}/Radarr.exe'.format(self.installdir)
        self.mono_path = '/usr/bin/mono'
        self.home_dir = '/home/{}'.format(self.user)
        self.config_dir = self.home_dir + '/.config/Radarr'
        self.database_file = self.config_dir + '/nzbdrone.db'
        self.config_file = self.config_dir + '/config.xml'
        self.service_name = 'radarr.service'
        self.service_file = '/etc/systemd/system/' + self.service_name
        self.kv = unitdata.kv()
        self.deps = [
            'libmono-cil-dev',
            'curl',
            'mediainfo',
        ]

    def modify_config(self, port=None, sslport=None, auth=None, urlbase=None):
        '''
        Modify the config.xml file for Radarr, this will cause a Radarr restart
        port: The value to use for the port, if not specifiedwill leave unmodified
        sslport: The value to use for the sslport, if not specified will leave unmodified
        auth: The value to use for Authentication, if not specified will leave unmodified
              Setting auth to 'None' will disable authenticaiton and is the only value tested for modifying the config
        urlbase: The value to use for the urlbase, if not specified will leave unmodified
                 Default urlbase is an empty string, passing a string of 'None' will set an empty string
        '''
        for line in fileinput.input(self.config_file, inplace=True):
            if line.strip().startswith('<Port>') and port:
                line = '  <Port>{}</Port>\n'.format(port)
            if line.strip().startswith('<UrlBase>') and urlbase:
                if urlbase == "None":
                    line = '  <UrlBase></UrlBase>\n'
                else:
                    line = '  <UrlBase>{}</UrlBase>\n'.format(urlbase)
            if line.strip().startswith('<SslPort>') and sslport:
                line = '  <SslPort>{}</SslPort>\n'.format(sslport)
            if line.strip().startswith('<AuthenticationMethod>') and auth:
                line = '  <AuthenticationMethod>{}</AuthenticationMethod>\n'.format(auth)
            print(line, end='')
        shutil.chown(self.config_file,
                     user=self.charm_config['radarr-user'],
                     group=self.charm_config['radarr-user'])
        host.service_restart(self.service_name)
        hookenv.log('Radarr config modified', 'INFO')

    def set_indexers(self, status):
        '''Enable or disable all indexer searching based on provided status
        status: True will turn on indexers
        status: False will turn off indexers'''
        conn = sqlite3.connect(self.database_file)
        c = conn.cursor()
        if status:
            c.execute('''UPDATE Indexers SET EnableRss = 1, EnableSearch = 1''')
        else:
            c.execute('''UPDATE Indexers SET EnableRss = 0, EnableSearch = 0''')
        conn.commit()
        host.chownr(self.home_dir, owner=self.charm_config['radarr-user'],
                    group=self.charm_config['radarr-user'])

    def setup_systemd(self):
        context = {'user': self.user,
                   'group': self.user,
                   'mono': self.mono_path,
                   'radarr': self.executable
                   }
        templating.render(source="{}.j2".format(self.service_name),
                          target=self.service_file,
                          context=context)
        host.service('enable', self.service_name)
        host.service('start', self.service_name)

    def setup_sabnzbd(self, port, apikey, hostname):
        host.service_stop(self.service_name)
        conn = sqlite3.connect(self.database_file)
        c = conn.cursor()
        c.execute('''SELECT Settings FROM DownloadClients WHERE ConfigContract is "SabnzbdSettings"''')
        result = c.fetchall()
        if len(result):
            hookenv.log("Modifying existing sabnzbd setting for Radarr", "INFO")
            row = result[0]
            settings = json.loads(row[0])
            settings['port'] = port
            settings['apiKey'] = apikey
            settings['host'] = hostname
            conn.execute('''UPDATE DownloadClients SET Settings = ? WHERE ConfigContract is "SabnzbdSettings"''',
                         (json.dumps(settings),))
        else:
            hookenv.log("Creating sabnzbd setting for Radarr.", "INFO")
            settings = {"tvCategory": "tv", "port": port, "apiKey": apikey,
                        "olderTvPriority": -100, "host": hostname, "useSsl": False, "recentTvPriority": -100}
            c.execute('''INSERT INTO DownloadClients
                      (Enable,Name,Implementation,Settings,ConfigContract) VALUES
                      (?,?,?,?,?)''',
                      (1, 'Sabnzbd', 'Sabnzbd', json.dumps(settings), 'SabnzbdSettings'))
        conn.commit()
        host.service_start(self.service_name)

    def setup_plex(self, hostname, port, user=None, passwd=None):
        '''' Modify an existing plex Notification or create one with the given settings
        hostname: The address for the plex server
        port: The plex port
        user: (Optional) plex user name
        passwd: (Optional) plex password'''
        host.service_stop(self.service_name)
        conn = sqlite3.connect(self.database_file)
        c = conn.cursor()
        c.execute('''SELECT Settings FROM Notifications WHERE ConfigContract is "PlexServerSettings"''')
        result = c.fetchall()
        if len(result):
            hookenv.log("Modifying existing plex setting for Radarr", "INFO")
            row = result[0]
            settings = json.loads(row[0])
            settings['host'] = hostname
            settings['port'] = port
            settings['username'] = settings['username'] or user
            settings['password'] = settings['password'] or passwd
            conn.execute('''UPDATE Notifications SET Settings = ? WHERE ConfigContract is "PlexServerSettings"''',
                         (json.dumps(settings),))
        else:
            hookenv.log("Creating plex setting for Radarr.", "INFO")
            settings = {"host": hostname, "port": port, "username": user or "", "password": passwd or "",
                        "updateLibrary": True, "useSsl": False, "isValid": True}
            c.execute('''INSERT INTO Notifications
                      (Name,OnGrab,onDownload,Settings,Implementation,ConfigContract,OnUpgrade,Tags,OnRename)
                      VALUES (?,?,?,?,?,?,?,?,?)''', ("Plex", 0, 1,
                                                      json.dumps(settings),
                                                      "PlexServer",
                                                      "PlexServerSettings", 1, None,
                                                      1))
        conn.commit()
        host.service_start(self.service_name)

    def install_deps(self):
        fetch.add_source("deb https://download.mono-project.com/repo/ubuntu stable-{series} main",
                         key="3FA7E0328081BFF6A14DA29AA6A19B38D3D831EF")
        self.kv.set('mono-source', 'mono-project')
        fetch.apt_update()
        fetch.apt_install(self.deps)

    def get_latest_release(self):
        '''
        Gets the latest Linux tarball release of Radarr
        returns: None on error, URL on success
        '''
        github = Github()
        releases = github.get_repo('Radarr/Radarr').get_releases()
        assets = releases[0].get_assets()

        for asset in list(assets):
            if asset.name.endswith('linux.tar.gz'):
                return asset.browser_download_url
        return None

    def configure_installdir(self):
        ''' Create and fix permissions on install dir'''
        if not os.path.exists(self.installdir):
            os.makedirs(self.installdir)
        uid = pwd.getpwnam(self.user).pw_uid
        gid = grp.getgrnam(self.user).gr_gid
        for root, dirnames, filenames in os.walk(self.installdir):
            os.chown(root, uid, gid)
            hookenv.log("Fixing data dir permissions: {}".format(
                root), 'DEBUG')
            for dirname in dirnames:
                os.chown(os.path.join(root, dirname), uid, gid)
            for filename in filenames:
                os.chown(os.path.join(root, filename), uid, gid)

    def update_radarr(self):
        ''' Unpacks downloaded Radarr build '''
        # recursive chown and make directory
        self.configure_installdir()

        # do the download and unpack
        url = self.get_latest_release()
        if url:
            fetch.install_remote(
                url,
                dest='/opt/'
            )

            # another recursive chown to fix permissions
            self.configure_installdir()
            return True
        return False

    def install_radarr(self):

        # make sure dependencies are installs
        self.install_deps()

        # make install dir if it doesn't exist
        self.configure_installdir()

        # download and unpack latest tarball
        self.update_radarr()

        # set up systemd unit
        self.setup_systemd()
