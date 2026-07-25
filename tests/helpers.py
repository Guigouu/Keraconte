"""Helpers et fixtures partagés par les tests du package quest_reader.

Séparés des tests eux-mêmes pour que le découpage en miroir des modules ne
duplique pas ce socle : les captures, les doublures et les fabriques de mots
servent à plusieurs fichiers de test à la fois.
"""

import pathlib
import types
from unittest import mock

import cv2

from quest_reader import Reader, clean
from quest_reader.detection import find_bubbles

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# Position des blocs dans chaque capture, relevée à la main.
BRAKMAR = {
    "file": "dialogue_brakmar.png",
    "dialogue": (1110, 490, 690, 270),
    "replies": (1110, 735, 690, 110),
    "expected": "C'est moi le plus grand, le plus magique, le plus doué des "
    "forgemages du monde. Mes armes sont surpuissantes et chacune est une "
    "pièce unique.",
}
TOKAGEKO = {
    "file": "dialogue_tokageko.png",
    "dialogue": (20, 40, 660, 140),
    "replies": (20, 180, 660, 220),
    "expected": "Pssst, approche-toi. Si tu as des badges d'expédition, j'ai "
    "quelques marchandises exclusives pour toi.",
}
# Thème bleu, adopté après les précédentes captures. Le gris neutre a
# disparu : la bulle y est à hue 117 pour un écart entre canaux de 23, là où
# le critère d'origine exigeait moins de 12. C'est la teinte qui l'isole.
THEME_BLEU = {
    "file": "dialogue_theme_bleu.png",
    "dialogue": (100, 166, 575, 101),
    "replies": (116, 287, 558, 79),
    "expected": "Tu ne vois pas que je suis en patrouille ? Va-t'en !",
}
SAMPLES = [BRAKMAR, TOKAGEKO, THEME_BLEU]
IDS = ["brakmar", "tokageko", "theme_bleu"]


def load(sample):
    frame = cv2.imread(str(FIXTURES / sample["file"]))
    assert frame is not None, f"fixture illisible : {sample['file']}"
    return frame


def erase(frame, box):
    """Recouvre une zone d'une couleur de décor, pour simuler son absence."""
    x, y, w, h = box
    frame = frame.copy()
    frame[y : y + h, x : x + w] = (90, 160, 90)
    return frame


def lecteur_nu(**etat):
    """Un Reader sans capture ni synthèse, pour éprouver « handle » seul.

    Construire le vrai demanderait le portail ScreenCast et un moteur vocal.
    """
    reader = Reader.__new__(Reader)
    reader.speaker = mock.Mock()
    reader.missing = 0
    reader.last_text = None
    reader.last_box = None
    reader.last_seen = 0.0
    reader.pending = []
    reader.args = types.SimpleNamespace(repeat_after=30)
    reader.__dict__.update(etat)
    return reader


def ecran(avec_bulle):
    """Une image de jeu, avec ou sans bulle à l'écran.

    « handle » interroge la présence de la bulle indépendamment du texte :
    l'OCR échoue souvent sur une bulle bien présente, et seule sa disparition
    doit couper la voix.
    """
    frame = load(THEME_BLEU)
    if avec_bulle:
        return frame
    return erase(erase(frame, THEME_BLEU["dialogue"]), THEME_BLEU["replies"])


def images(reader, textes, bulle_presente=False):
    """Fait défiler des images devant le lecteur, une par texte.

    Par défaut, une image sans texte est une image sans bulle — le joueur a
    fermé la fenêtre. « bulle_presente » simule au contraire un OCR muet
    devant une bulle toujours affichée.

    On ne simule que l'OCR (« find_dialog_box ») : la présence de la bulle,
    elle, est jugée sur la vraie image par le code réel, sur laquelle repose
    la coupure. La boîte rendue est celle que « find_bubbles » voit sur cette
    image, pour que le lecteur retrouve la même à l'image suivante.
    """
    boite = find_bubbles(load(THEME_BLEU))[0][0]
    for texte in textes:
        frame = ecran(texte is not None or bulle_presente)
        resultat = (texte, boite) if texte is not None else (None, None)
        with mock.patch(
            "quest_reader.reader.find_dialog_box", return_value=resultat
        ):
            reader.handle(frame)
    return [appel.args[0] for appel in reader.speaker.say.call_args_list]


class FauxProcessus:
    """Tient le rôle de paplay : on veut savoir s'il a été interrompu."""

    def __init__(self):
        self.tue = False

    def terminate(self):
        self.tue = True

    def wait(self):
        return 0


CLIQUETIS = {
    "file": "dialogue_cliquetis.png",
    "expected": "*Cliquetis* “Quetis,Cliquetis* *Cliquetis*-*Cliquecliquetis*, "
    "*Clicliquetis*",
}
ENROLEMENT = {
    "file": "dialogue_enrolement.png",
    "expected": "Tiens donc, une âme neutre en ces lieux, Je te conseille de "
    "t'enrôler pour Brâkmar, le mal est toujours plus amusant. Si ça "
    "t'intéresse, ramène-moi 10 dagues de boisaille. Elles serviront à "
    "entraîner les bras cassés dont tu feras vite partie.",
}


def mots_places(lignes):
    """Fabrique des mots à la manière de « read_words » : un couple
    (ordonnée, phrase) par ligne. Les ordonnées reprennent celles relevées
    sur la capture « enrolement » — interligne de 20 px, puis 95 px avant
    le premier choix."""
    mots = []
    for rang, (top, phrase) in enumerate(lignes):
        for numero, texte in enumerate(phrase.split()):
            mots.append({"text": texte, "top": top, "order": (rang, 1, 1, numero)})
    return mots


def texte_de(mots):
    return clean(" ".join(mot["text"] for mot in mots))


KLAKO = {
    "file": "dialogue_klako.png",
    "expected": "Bonjour Tryvia. Je suis Klako, un des meilleurs chasseurs "
    "de dragodindes de la région. Bienvenue !",
}


# Relevé en jeu chez Roukerol de Nerouz. La bulle et le bloc de réponses se
# touchent : la morphologie les fond en un seul contour de hauteur 314, sous
ROUKEROL = {
    "file": "dialogue_roukerol.png",
    "expected": "Le bricolage, il y a ceux qui savent faire et qui aiment ça. "
    "Des gens comme moi, en somme. Il y a ceux qui ne savent pas faire, et "
    "qui n'aiment pas ça. Je peux le comprendre, chacun ses goûts. Et il y a "
    "ceux qui ne savent pas faire, et qui aiment ça. Ce sont les plus "
    "dangereux.",
}


# Dialogue très court, apparié à ses réponses. « expected » reprend ce que
# l'OCR rend vraiment (« toâ » ressort « toû. »), non le texte à l'écran.
# Capture PLEINE (2560×1346) : chat et barre de sorts sont à l'écran, ce
# qu'un crop ne contient pas — indispensable pour éprouver la coupure, que
# ces panneaux permanents empêchaient. « dialogue »/« replies » sont au
# format de « erase » (x, y, w, h), pour simuler la fermeture de la fenêtre.
BWORKIDAIS = {
    "file": "dialogue_bworkidais.png",
    "expected": "Zog Zog à toû.",
    "dialogue": (1109, 333, 576, 102),
    "replies": (1125, 457, 559, 113),
}


def faux_xtts(rendus):
    """Remplace torch, transformers et TTS par des doublures.

    Le venv du projet n'a pas torch — trois gigaoctets pour un test — et
    charger le vrai modèle prend 83 s. On vérifie donc le câblage du moteur,
    pas la synthèse elle-même, qui l'est à la main dans un venv à part.
    """

    class FauxTTS:
        def __init__(self, model):
            rendus["model"] = model

        def to(self, device):
            rendus["device"] = device
            return self

        def tts_to_file(self, **kwargs):
            rendus.setdefault("appels", []).append(kwargs)

    torch = types.ModuleType("torch")
    torch.isin = lambda elements, test_elements: (elements, test_elements)
    torch.cuda = types.SimpleNamespace(is_available=lambda: True)
    pu = types.ModuleType("transformers.pytorch_utils")
    transformers = types.ModuleType("transformers")
    transformers.pytorch_utils = pu
    api = types.ModuleType("TTS.api")
    api.TTS = FauxTTS
    tts_module = types.ModuleType("TTS")
    tts_module.api = api
    return {
        "torch": torch,
        "transformers": transformers,
        "transformers.pytorch_utils": pu,
        "TTS": tts_module,
        "TTS.api": api,
    }, pu


# Relevé en jeu chez Djaul. L'OCR permute parfois les lignes, quand l'image
# est saisie pendant un rafraîchissement de la bulle.
HERCULE = (
    "Le commanditaire est peut-être un collectionneur, un sorcier, un mage "
    "artisan ou encore un alchimiste. Dans ce cas, il doit y avoir des rumeurs "
    "circulant sur l'achat de la relique au marché noir. Pars en discuter avec "
    "Hercule Poivrot à la taverne de Djaul, c'est un espion de l'Ordre de "
    "l'Œil Putride."
)
HERCULE_PERMUTE = (
    "espion de l'Ordre de l'Œil Putride. Le commanditaire est peut-être un "
    "collectionneur, un sorcier, un mage artisan ou encore un alchimiste. Dans "
    "ce cas, il doit y avoir des rumeurs circulant sur l'achat de la relique "
    "au marché noir."
)
