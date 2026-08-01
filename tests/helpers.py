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
from quest_reader.speed import Vitesse

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# Position des blocs dans chaque capture, relevée à la main.
BRAKMAR = {
    "file": "dialogues/dialogue_brakmar.png",
    "dialogue": (1110, 490, 690, 270),
    "replies": (1110, 735, 690, 110),
    "expected": "C'est moi le plus grand, le plus magique, le plus doué des "
    "forgemages du monde. Mes armes sont surpuissantes et chacune est une "
    "pièce unique.",
}
TOKAGEKO = {
    "file": "dialogues/dialogue_tokageko.png",
    "dialogue": (20, 40, 660, 140),
    "replies": (20, 180, 660, 220),
    "expected": "Pssst, approche-toi. Si tu as des badges d'expédition, j'ai "
    "quelques marchandises exclusives pour toi.",
}
# Thème bleu, adopté après les précédentes captures. Le gris neutre a
# disparu : la bulle y est à hue 117 pour un écart entre canaux de 23, là où
# le critère d'origine exigeait moins de 12. C'est la teinte qui l'isole.
THEME_BLEU = {
    "file": "dialogues/dialogue_theme_bleu.png",
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
    reader.vitesse = Vitesse(1.22)
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


class FauxSortie:
    """Tient le rôle du flux sounddevice : enregistre les tranches écrites.

    « paplay » jouait un fichier d'un bloc ; on lit désormais par tranches et
    on écrit chacune dans un « OutputStream ». On veut savoir combien de
    tranches sont parties (donc si la lecture s'est bien abandonnée à un
    changement de génération) et si le flux a été fermé proprement.
    """

    def __init__(self):
        self.tranches = 0
        self.ferme = False

    def start(self):
        pass

    def write(self, tranche):
        self.tranches += 1

    def stop(self):
        pass

    def close(self):
        self.ferme = True


CLIQUETIS = {
    "file": "dialogues/dialogue_cliquetis.png",
    "expected": "*Cliquetis* “Quetis,Cliquetis* *Cliquetis*-*Cliquecliquetis*, "
    "*Clicliquetis*",
}
ENROLEMENT = {
    "file": "dialogues/dialogue_enrolement.png",
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
    "file": "dialogues/dialogue_klako.png",
    "expected": "Bonjour Tryvia. Je suis Klako, un des meilleurs chasseurs "
    "de dragodindes de la région. Bienvenue !",
}


# Relevé en jeu chez Roukerol de Nerouz. La bulle et le bloc de réponses se
# touchent : la morphologie les fond en un seul contour de hauteur 314, sous
ROUKEROL = {
    "file": "dialogues/dialogue_roukerol.png",
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
    "file": "dialogues/dialogue_bworkidais.png",
    "expected": "Zog Zog à toû.",
    "dialogue": (1109, 333, 576, 102),
    "replies": (1125, 457, 559, 113),
}


# Relevé en jeu chez Bworknroll. Le bandeau du haut de bulle (⋮ à gauche, ✕
# à droite) sortait à l'OCR en « ë - » AU-DESSUS du texte, avec une confiance
# qui les faisait passer « keep_word » : ils se collaient en tête de chaque
# réplique lue. « drop_top_chrome » les retire par géométrie. « expected »
# reprend ce que l'OCR rend vraiment (le « : » après « commencer » saute, le
# bruit intra-ligne « _kd'à » subsiste — hors du périmètre de ce correctif),
# non le texte à l'écran.
BWORKNROLL = {
    "file": "dialogues/dialogue_bworknroll.png",
    "expected": "Pour commencer des canines de Gobelin, des cheveux de Sadida "
    "et des os de Trooll. Voilà un scalpel qui te permettra de désosser un "
    "Trooll. Il y en a dans le donjon _kd'à côté ou dans la fosse.",
}


# Relevé en jeu chez L'Explorancienne, à l'échelle d'interface 100 % / police
# « Moyen ». À cette échelle, la fermeture morphologique soude la bulle à son
# bloc de réponses : le bloc n'est plus apparié d'emblée, il n'est admis que
# par « splits_into_pair ». Ce dialogue narratif est peu ponctué (2 points sur
# 28 mots, ratio 0,07 < MIN_PUNCTUATION_RATIO) : « reads_like_dialogue » le
# rejetait, alors que la re-segmentation avait bel et bien prouvé la paire.
# Verrouille le correctif : une preuve relationnelle (paire re-segmentée) fait
# sauter le test de ponctuation, au même titre qu'un appariement d'emblée. Le
# « - » de tête est du chrome OCR non retiré (bandeau ⋮ mal lu), hors périmètre
# de ce correctif — « expected » reprend ce que l'OCR rend vraiment.
EXPLORANCIENNE_100 = {
    "file": "echelle/explorancienne_100_moyen.png",
    "expected": "- Le moment est venu pour les Douziens de partir à la "
    "découverte des mondes qui les entourent. L'exploration nourrit la "
    "connaissance qui mène à la compréhension du Krosmoz.",
}


# Relevé en jeu chez Hazel Ementaire (plein écran fenêtré 2710×1539), dont la
# réponse unique « S'en aller. » tient sur UNE seule ligne. Ce bloc de réponses
# ne fait que ~36000 px² : sous « MIN_AREA », « find_bubbles » ne le rend jamais
# comme contour, l'appariement ne le voit pas, et le dialogue passait inaperçu
# (« pas-de-preuve », ocr=0ms). « find_reply_below » le rattrape en re-segmentant
# la bande sous la bulle sans plancher d'aire. Verrouille ce cas : une réponse
# MONO-ligne, séparée de sa bulle, doit être appariée comme une réponse
# multi-lignes le serait. Le chat (coin bas-gauche) est masqué avant commit.
HAZEL = {
    "file": "dialogues/dialogue_hazel.png",
    "expected": "La cité des Mercenaires est le premier endroit visité par les "
    "âmes venues d'Incarnam. C'est un lieu où il se passe toujours quelque "
    "chose ! Le commerce et l'artisanat sont florissants. Si tu as besoin de "
    "t'équiper pour partir à l'aventure, tu devrais trouver ce qu'il te faut "
    "sans trop de difficultés.",
}


# Le MÊME dialogue PNJ (« Gardien des Geôles d'Astrub »), capturé sous trois
# thèmes de palettes distinctes (brakmar sombre, bonta clair, wabbit coloré)
# en fenêtré 2710×1539. Ce dialogue n'a qu'UNE option de réponse : son bloc de
# réponses ne fait que ~43800 px² (contre 54000-63000 pour un dialogue à
# plusieurs réponses). Il restait au-dessus d'un plancher absolu de 40000, mais
# un seuil d'aire alors rapporté à l'aire de l'image montait à 48000 px² avec la
# taille de la fenêtre et l'écartait : plus d'appariement, dialogue inaperçu
# dans TOUS les thèmes. Le seuil est désormais absolu (MIN_AREA), indépendant de
# la fenêtre. Le texte lu est identique aux trois thèmes : la couleur du thème
# n'influe pas sur l'OCR, seule la géométrie comptait. Le panneau de chat (coin
# bas-gauche) est masqué en noir avant commit.
THEME_GARDIEN = {
    "files": [
        "themes/brakmar.png",
        "themes/bonta.png",
        "themes/wabbit.png",
        "themes/belladone.png",
        "themes/emerald_mine.png",
        "themes/gold_and_steel.png",
        "themes/pandala.png",
        "themes/sufokia.png",
    ],
    # Deux captures de thème restent versionnées mais HORS de ce test d'égalité :
    #  - « tribute.png » montre un autre PNJ (« Ici sont enfermés les pires
    #    chenapans… »), pas le dialogue de la clé à molette ;
    #  - « unicorn.png » lit bien le bon dialogue, mais l'OCR y rend une
    #    apostrophe droite (« qu'elle ») là où les autres rendent la courbe
    #    (« qu'elle ») : la détection est correcte, seule l'égalité stricte de
    #    texte échoue. Le test vérifie la détection, pas la fidélité d'apostrophe.
    "expected": "Lorsque vous saisissez la clé à molette, un léger frémissement "
    "vous parcourt. Une étrange énergie émane du métal, comme si l’objet "
    "cherchait à réagir à votre présence. En la laissant tomber "
    "accidentellement, vous remarquez qu’elle rebondit d’une manière étrange, "
    "produisant un tintement métallique presque mélodieux. Une vieille relique "
    "ou un artefact magique oublié ?",
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
