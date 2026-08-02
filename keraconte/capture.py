"""Capture d'écran via le portail xdg-desktop-portal (Wayland).

Ouvre un flux PipeWire et remet un descripteur au lecteur. Ne dépend que de
dbus : le décodage vidéo (Gst) vit dans « reader ».
"""

import os

import dbus

TOKEN_FILE = os.path.expanduser("~/.cache/keraconte/restore-token")


def forget_token():
    """Oublie l'autorisation mémorisée, pour que le sélecteur réapparaisse.

    Sans ça, le portail réutilise le jeton et re-sélectionner une source ne
    montrerait jamais de boîte de choix.
    """
    try:
        os.remove(TOKEN_FILE)
    except OSError:
        pass


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
        # Receveurs de signaux ouverts, à retirer à la fermeture : sans ça, une
        # re-sélection les accumulerait à chaque session.
        self._receivers = []

    def _request(self, callback):
        self.counter += 1
        token = f"qr{self.counter}"
        path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        receiver = self.bus.add_signal_receiver(
            callback,
            signal_name="Response",
            dbus_interface="org.freedesktop.portal.Request",
            path=path,
        )
        self._receivers.append(receiver)
        return token

    def close(self):
        """Ferme la session portail et retire les receveurs de signaux.

        Appelé avant de recréer une session (re-sélection de la source) :
        laisser l'ancienne vivante ferait entrer en collision son chemin
        d'objet avec la nouvelle côté portail.
        """
        if self.session is not None:
            try:
                self.bus.get_object(
                    "org.freedesktop.portal.Desktop", self.session
                ).Close(dbus_interface="org.freedesktop.portal.Session")
            except dbus.DBusException:
                pass  # session déjà close côté portail : rien à faire
            self.session = None
        for receiver in self._receivers:
            try:
                receiver.remove()
            except Exception:
                pass
        self._receivers = []

    def start(self):
        token = self._request(self._on_session)
        # Jeton de session unique par appel : redemander une source (bouton de
        # re-sélection) recrée une session, et réutiliser « qrsession » entrait
        # en collision avec la précédente encore vivante côté portail.
        self.counter_session = getattr(self, "counter_session", 0) + 1
        self.portal.CreateSession(
            {
                "session_handle_token": f"qrsession{self.counter_session}",
                "handle_token": token,
            },
            dbus_interface="org.freedesktop.portal.ScreenCast",
        )

    def _on_session(self, code, results):
        if code != 0:
            # Non fatal : sur un thread GLib, « sys.exit » ne quitte pas le
            # processus (traceback puis boucle qui continue). On signale et on
            # laisse l'état précédent en place — la capture en cours survit.
            print("Création de session refusée.")
            return
        self.session = results["session_handle"]
        token = self._request(self._on_sources)
        options = {
            # 1 = écran, 2 = fenêtre : proposer les deux dans le sélecteur, pour
            # pouvoir attraper directement la fenêtre du jeu.
            "types": dbus.UInt32(1 | 2),
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
            # Annulation du sélecteur = action normale (bouton de re-sélection).
            print("Sélection de source annulée.")
            return
        token = self._request(self._on_started)
        self.portal.Start(
            self.session,
            "",
            {"handle_token": token},
            dbus_interface="org.freedesktop.portal.ScreenCast",
        )

    def _on_started(self, code, results):
        if code != 0:
            print("Partage d'écran annulé.")
            return
        if "restore_token" in results:
            self._save_token(str(results["restore_token"]))
        streams = results["streams"]
        if not streams:
            print("Aucun flux renvoyé par le portail.")
            return
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
