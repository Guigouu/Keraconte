"""Capture d'écran via le portail xdg-desktop-portal (Wayland).

Ouvre un flux PipeWire et remet un descripteur au lecteur. Ne dépend que de
dbus : le décodage vidéo (Gst) vit dans « reader ».
"""

import os
import sys

import dbus

TOKEN_FILE = os.path.expanduser("~/.cache/quest-reader/restore-token")


class ScreenCast:
    """Ouvre un flux PipeWire via le portail xdg-desktop-portal.

    Le jeton de restauration évite de redemander l'autorisation à chaque
    lancement : la boîte de dialogue n'apparaît qu'une seule fois.
    """

    def __init__(self, on_node):
        self.on_node = on_node
        self.bus = dbus.SessionBus()
        self.portal = self.bus.get_object(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop"
        )
        self.session = None
        unique = self.bus.get_unique_name()[1:].replace(".", "_")
        self.sender = unique
        self.counter = 0

    def _request(self, callback):
        self.counter += 1
        token = f"qr{self.counter}"
        path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        self.bus.add_signal_receiver(
            callback,
            signal_name="Response",
            dbus_interface="org.freedesktop.portal.Request",
            path=path,
        )
        return token

    def start(self):
        token = self._request(self._on_session)
        self.portal.CreateSession(
            {
                "session_handle_token": "qrsession",
                "handle_token": token,
            },
            dbus_interface="org.freedesktop.portal.ScreenCast",
        )

    def _on_session(self, code, results):
        if code != 0:
            sys.exit("Création de session refusée.")
        self.session = results["session_handle"]
        token = self._request(self._on_sources)
        options = {
            "types": dbus.UInt32(1),  # écrans uniquement
            "multiple": False,
            "handle_token": token,
            "persist_mode": dbus.UInt32(2),  # mémoriser l'autorisation
        }
        saved = self._load_token()
        if saved:
            options["restore_token"] = saved
        self.portal.SelectSources(
            self.session, options, dbus_interface="org.freedesktop.portal.ScreenCast"
        )

    def _on_sources(self, code, results):
        if code != 0:
            sys.exit("Sélection de source refusée.")
        token = self._request(self._on_started)
        self.portal.Start(
            self.session,
            "",
            {"handle_token": token},
            dbus_interface="org.freedesktop.portal.ScreenCast",
        )

    def _on_started(self, code, results):
        if code != 0:
            sys.exit("Partage d'écran refusé.")
        if "restore_token" in results:
            self._save_token(str(results["restore_token"]))
        streams = results["streams"]
        if not streams:
            sys.exit("Aucun flux renvoyé par le portail.")
        node_id = int(streams[0][0])
        fd = self.portal.OpenPipeWireRemote(
            self.session, {}, dbus_interface="org.freedesktop.portal.ScreenCast"
        )
        self.on_node(fd.take(), node_id)

    def _load_token(self):
        try:
            with open(TOKEN_FILE) as handle:
                return handle.read().strip()
        except OSError:
            return None

    def _save_token(self, token):
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w") as handle:
            handle.write(token)
