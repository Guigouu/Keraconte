"""Tests de détection et de nettoyage, sur de vraies captures de Dofus.

Les cas négatifs sont fabriqués en masquant une partie d'une capture réelle
plutôt qu'à partir d'images inventées : les couleurs du jeu restent donc
présentes autour de la zone effacée.
"""

import pathlib
import sys
import time
import types
from unittest import mock

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader import Reader, Speaker  # noqa: E402
from quest_reader.detection import (  # noqa: E402
    drop_replies,
    find_dialog,
    keep_word,
    reads_like_dialogue,
)
from quest_reader.text import clean, same_dialog  # noqa: E402
from tests.helpers import (  # noqa: E402
    BRAKMAR,
    CLIQUETIS,
    ENROLEMENT,
    FIXTURES,
    IDS,
    KLAKO,
    ROUKEROL,
    SAMPLES,
    THEME_BLEU,
    TOKAGEKO,
    FauxProcessus,
    ecran,
    erase,
    faux_xtts,
    images,
    lecteur_nu,
    load,
    mots_places,
    texte_de,
)


@pytest.mark.parametrize("sample", SAMPLES, ids=IDS)
def test_lit_le_dialogue(sample):
    assert clean(find_dialog(load(sample))) == sample["expected"]


@pytest.mark.parametrize("sample", SAMPLES, ids=IDS)
def test_ignore_sans_bulle(sample):
    frame = erase(load(sample), sample["dialogue"])
    assert find_dialog(frame) is None


@pytest.mark.parametrize("sample", SAMPLES, ids=IDS)
def test_ignore_sans_bloc_de_reponses(sample):
    """Sans réponses en dessous, ce n'est pas un dialogue de PNJ."""
    frame = erase(load(sample), sample["replies"])
    assert find_dialog(frame) is None


@pytest.mark.parametrize("sample", SAMPLES, ids=IDS)
def test_empreinte_stable_malgre_le_bruit(sample):
    """Le même dialogue ne doit être lu qu'une fois.

    L'OCR laisse des fragments parasites variables autour du texte ; c'est
    ce qui provoquait une relecture en boucle.
    """
    frame = load(sample)
    rng = np.random.default_rng(0)
    for index in range(25):
        noisy = frame
        if index:
            noise = rng.integers(-3, 4, frame.shape, dtype=np.int16)
            noisy = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        text = find_dialog(noisy)
        if text:
            assert same_dialog(clean(text), sample["expected"])


# Les fragments d'icônes ne se reconnaissent plus par leur forme écrite mais
# au mot, avec la confiance de l'OCR. Les confiances ci-dessous sont celles
# relevées sur les fixtures via image_to_data ; les cas restent les mêmes,
# seul leur point d'entrée change.
@pytest.mark.parametrize(
    "texte, confiance",
    [
        ("E", 36),  # brakmar
        ("e", 43),  # brakmar
        (":", 50),  # brakmar
        ("x", 95),  # brakmar : bien noté, mais sans voyelle et isolé
        ("PE", 24),  # cliquetis
        ("A", 44),  # cliquetis
        ("R", 93),  # tokageko : bien noté, rejeté sur la structure
        ("SE", 30),  # paires de capitales laissées par les icônes
        ("2E", 40),  # chiffre et capitale collés
        ("3A", 40),
        ("A3", 40),  # vu en plein milieu de phrase, pas seulement aux bords
        ("»/", 30),
        ("SN", 30),
        ("dn", 30),
        ("2S", 30),
        ("Â", 30),
        ("Ë", 30),
        ("_", 30),
        ("CON", 30),
    ],
)
def test_keep_word_rejette_le_bruit_d_icone(texte, confiance):
    assert not keep_word(texte, confiance)


@pytest.mark.parametrize(
    "texte, confiance",
    [
        ("C'est", 92),  # élision : l'apostrophe rend le mot plausible
        ("t'enrôler", 41),  # vrai mot mal noté, sauvé par sa longueur
        ("lieux,", 53),
        ("Si", 83),  # vrais mots courts, tous bien notés
        ("tu", 83),
        ("as", 91),
        ("à", 96),
        ("Œuvre", 80),
        ("NORD.", 80),  # un vrai mot en capitales appartient à la phrase
        ("STOP.", 80),
        ("Pssst,", 91),  # onomatopée sans voyelle, mais longue et bien notée
        ("*Cliquetis*", 87),
    ],
)
def test_keep_word_garde_les_vrais_mots(texte, confiance):
    assert keep_word(texte, confiance)


@pytest.mark.parametrize("nombre", ["10", "5", "6", "20"])
def test_keep_word_garde_toujours_les_nombres(nombre):
    """Les nombres portent les quantités de quête : les taire prive le
    joueur de l'information. La garde passe avant le test de structure,
    qui les rejetterait faute de voyelle."""
    assert keep_word(nombre, 30)


def test_keep_word_laisse_passer_un_nombre_parasite():
    """Contrepartie assumée de la garde ci-dessus : un « 64 » venu d'une
    icône est indiscernable d'une quantité de quête. Le plan le classait
    comme du bruit à rejeter ; la contrainte sur les nombres l'emporte, un
    mot lu en trop coûtant moins qu'une quantité tue."""
    assert keep_word("64", 30)


def test_le_speaker_s_arrete_sans_vider_sa_file():
    """Après un Ctrl+C, le reste de la file ne doit plus être synthétisé.

    Le thread est « daemon » : s'il survit à l'arrêt, il rappelle espeak
    pendant que l'interpréteur détruit les dossiers temporaires, d'où la
    cascade de « [Errno 2] libespeak-ng.so » — une par élément restant.
    """

    dits = []

    class MoteurFactice:
        def speak(self, texte, narration):
            dits.append(texte)

    speaker = Speaker(MoteurFactice)
    speaker.start()
    speaker.say("Premier.")
    speaker.say("Deuxième.")
    speaker.stop()

    assert not speaker.is_alive()
    # La file est purgée, pas jouée jusqu'au bout : l'arrêt est immédiat.
    assert dits == [] or dits == ["Premier."]


# Le dialogue du rototo, relevé en jeu : Dofus l'écrit progressivement, et
# l'OCR l'attrape à plusieurs stades. Il avait été lu huit fois de suite.
ROTOTO_DEBUT = (
    "Beeeuuuurp ! Ça fait un bien fou ! Désolé de t'avoir décoiffé. Un "
    "dresseur a craché le morceau il a indiqué à sa conquête d'un soir "
    "comment apaiser le molosse."
)
ROTOTO_ENTIER = ROTOTO_DEBUT + " À mon avis, il ne lui reste plus très longtemps à vivre…"
ROTOTO_BRUITE = (
    ROTOTO_DEBUT + " À mon avis, il ne lui reste plus très —L|nngremps à vivre…"
)


def test_un_dialogue_en_cours_d_ecriture_n_est_lu_qu_une_fois():
    """Vu en jeu : huit lectures pour une seule réplique.

    Dofus affiche le texte progressivement. Chaque état intermédiaire
    tombait sous le seuil de similarité — 0,85 entre le début et la réplique
    entière — et repartait donc en lecture.
    """
    reader = lecteur_nu()
    lus = images(reader, [ROTOTO_DEBUT, ROTOTO_BRUITE, ROTOTO_DEBUT, ROTOTO_BRUITE])
    assert len(lus) == 1


def test_c_est_la_replique_entiere_qui_est_lue():
    """Le début seul ne doit jamais être dit : sa fin ne viendrait jamais."""
    reader = lecteur_nu()
    lus = images(reader, [ROTOTO_DEBUT, ROTOTO_ENTIER, ROTOTO_ENTIER])
    assert lus == [ROTOTO_ENTIER]


def test_la_variante_la_moins_abimee_l_emporte():
    """À longueur égale, préférer la lecture sans caractères parasites."""
    reader = lecteur_nu()
    lus = images(reader, [ROTOTO_BRUITE, ROTOTO_ENTIER, ROTOTO_ENTIER])
    assert lus == [ROTOTO_ENTIER]


def test_deux_repliques_successives_sont_toutes_deux_lues():
    """L'attente de stabilisation ne doit pas avaler le dialogue suivant."""
    reader = lecteur_nu()
    suivant = "Il s'appelle Pascal Obistro et travaille à la taverne."
    lus = images(reader, [ROTOTO_ENTIER, ROTOTO_ENTIER, suivant, suivant])
    assert lus == [ROTOTO_ENTIER, suivant]


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
CUISINE = (
    "Ne sois pas autant pressé ! Des travaux pour aménager des cavernes "
    "étaient en cours non loin du lieu du cambriolage. Après avoir discuté "
    "avec Hercule Poivrot, tu iras interroger le chef de chantier. Je l'ai "
    "convoqué en cuisine."
)
CUISINE_REPONSES = CUISINE + " ! ? 5 ? Suivre les ordres."


def test_des_lignes_permutees_restent_le_meme_dialogue():
    """L'OCR intervertit les lignes d'une image à l'autre.

    Le ratio de séquence tombe alors à 0,74 et la réplique repartait en
    lecture ; le vocabulaire, lui, ne change pas.
    """
    assert same_dialog(clean(HERCULE), clean(HERCULE_PERMUTE))


def test_un_dialogue_aux_lignes_permutees_n_est_lu_qu_une_fois():
    """Six images alternant les deux lectures, une seule réplique dite."""
    reader = lecteur_nu()
    lus = images(
        reader,
        [HERCULE, HERCULE_PERMUTE, HERCULE, HERCULE_PERMUTE, HERCULE, HERCULE],
    )
    assert len(lus) == 1


def test_les_reponses_du_joueur_ne_sont_pas_dites():
    """« drop_replies » laisse parfois passer les choix, collés au dialogue.

    Vu en jeu : « Je l'ai convoqué en cuisine. ! ? 5 ? Suivre les ordres. »
    Aucun critère textuel ne distingue « Insister. » d'une phrase de PNJ —
    c'est pourquoi le tri se fait sur la géométrie. Ici, on refuse seulement
    de suivre la lecture qui dépasse nettement les autres.
    """
    reader = lecteur_nu()
    lus = images(reader, [CUISINE, CUISINE, CUISINE_REPONSES, CUISINE])
    assert lus == [clean(CUISINE)]


def test_une_bulle_absente_une_seule_image_ne_coupe_pas():
    """Un fondu ou une fenêtre qui passe devant ne doit pas hacher la lecture."""
    reader = lecteur_nu(last_text="Bonjour, aventurier.")
    images(reader, [None] * (Reader.CLOSED_AFTER - 1))
    reader.speaker.silence.assert_not_called()


def test_la_bulle_fermee_coupe_la_dictee():
    """Après assez d'images sans bulle, la voix s'arrête et la file se vide."""
    reader = lecteur_nu(last_text="Bonjour, aventurier.")
    images(reader, [None] * Reader.CLOSED_AFTER)

    reader.speaker.silence.assert_called_once()
    # Le texte reste en mémoire : trois images sans lecture ne prouvent pas
    # que la bulle a été fermée, et l'oublier faisait tout relire au retour.
    assert reader.last_text == "Bonjour, aventurier."


def test_un_ocr_qui_rate_quelques_images_ne_fait_pas_relire():
    """Vu en jeu : un dialogue lu quatre fois d'affilée.

    Sur une réplique longue, « find_dialog » échoue par intermittence —
    rafraîchissement, animation. Trois échecs suffisaient à effacer la
    mémoire du texte, et la réplique repartait en lecture au retour.
    """
    reader = lecteur_nu()
    texte = "Tu veux savoir pourquoi je rigole ? Donne-moi 5 kamas."
    trou = [None] * Reader.CLOSED_AFTER
    lus = images(reader, [texte] * 2 + trou + [texte] * 2 + trou + [texte] * 2)
    assert lus == [clean(texte)]


def test_un_ocr_muet_devant_une_bulle_presente_ne_coupe_pas_la_voix():
    """Vu en jeu : la voix s'arrête au milieu, bulle inchangée à l'écran.

    L'OCR échoue régulièrement sur une bulle bien affichée — texte en cours
    d'écriture, rafraîchissement. Couper là-dessus arrêtait la réplique sans
    jamais reprendre : au retour, le texte est reconnu comme déjà lu.
    """
    reader = lecteur_nu()
    texte = "Tu ne vois pas que je suis en patrouille ?"
    images(reader, [texte] * 2 + [None] * 6 + [texte] * 2, bulle_presente=True)
    reader.speaker.silence.assert_not_called()


def test_la_bulle_qui_quitte_l_ecran_coupe_toujours():
    """La tolérance ci-dessus ne doit pas désarmer la coupure elle-même."""
    reader = lecteur_nu()
    texte = "Tu ne vois pas que je suis en patrouille ?"
    images(reader, [texte] * 2 + [None] * Reader.CLOSED_AFTER)
    reader.speaker.silence.assert_called_once()


def test_rouvrir_le_dialogue_plus_tard_le_relit():
    """La tolérance ci-dessus ne doit pas rendre un PNJ définitivement muet."""
    reader = lecteur_nu()
    texte = "Tu ne vois pas que je suis en patrouille ?"
    lus = images(reader, [texte] * 2)
    # Le joueur revient bien après le délai de relecture.
    reader.last_seen -= reader.args.repeat_after + 1
    lus = images(reader, [None] * Reader.CLOSED_AFTER + [texte] * 2)
    assert len(lus) == 2


def test_la_coupure_n_est_ordonnee_qu_une_fois():
    """Rester devant un écran sans bulle ne doit pas marteler « silence »."""
    reader = lecteur_nu()
    images(reader, [None] * (Reader.CLOSED_AFTER * 4))
    reader.speaker.silence.assert_called_once()


def test_une_bulle_qui_revient_annule_le_decompte():
    """Deux images sans bulle puis une avec : rien ne doit être coupé."""
    reader = lecteur_nu()
    manquantes = [None] * (Reader.CLOSED_AFTER - 1)
    images(reader, manquantes + ["Me revoilà."] + manquantes)
    reader.speaker.silence.assert_not_called()


def test_la_file_du_speaker_ne_grossit_pas_sans_fin():
    """Empiler pendant le chargement du moteur ne doit rien accumuler.

    XTTS met 83 s à charger, et « run » ne dépile rien pendant ce temps.
    Avec une file non bornée, tout ce que la capture voyait s'y entassait,
    puis partait en rafale à la fin du chargement : c'est ce qui a rempli
    la mémoire de la machine.
    """

    speaker = Speaker(lambda: None)  # jamais démarré : personne ne dépile

    for numero in range(50):
        speaker.say(f"Réplique numéro {numero}.")

    assert speaker.queue.qsize() <= Speaker.BACKLOG


def test_say_ne_bloque_pas_le_fil_de_capture():
    """Une file pleine doit rendre la main, pas figer l'écran.

    « say » est appelé depuis la boucle de capture : s'il bloque, la
    capture s'arrête avec lui.
    """

    speaker = Speaker(lambda: None)
    for numero in range(Speaker.BACKLOG + 3):
        speaker.say(f"Réplique {numero}.")

    debut = time.monotonic()
    speaker.say("Celle-ci est de trop.")
    assert time.monotonic() - debut < 0.5


@pytest.mark.parametrize(
    "mots, attendu",
    [
        (
            [("SE", 30), ("x", 49), ("L'élevage", 90), ("des", 90),
             ("dragodindes,", 90), ("c'est", 90), ("ma", 90), ("grande", 90),
             ("passion.", 90)],
            "L'élevage des dragodindes, c'est ma grande passion.",
        ),
        (
            [("E", 36), ("x", 49), ("On", 90), ("me", 90), ("considère", 90),
             ("comme", 90), ("le", 90), ("meilleur", 90), ("éleveur.", 90)],
            "On me considère comme le meilleur éleveur.",
        ),
    ],
)
def test_retire_les_paires_de_capitales(mots, attendu):
    """Les icônes sortent aussi en paires de capitales : « SE x »."""
    assert filtre(mots) == attendu


def test_speed_accelere_les_deux_moteurs():
    """« --speed » est un débit : au-dessus de 1, la parole va plus vite.

    Piper raisonne à l'inverse, en durée. Sans cette inversion, un même
    chiffre accélérait un moteur et ralentissait l'autre.
    """
    import quest_reader

    rendus = {}

    class FauxPiper:
        @staticmethod
        def load(path):
            return None

    def faux_config(length_scale):
        rendus["length_scale"] = length_scale
        return None

    faux_module = types.ModuleType("piper")
    faux_module.PiperVoice = FauxPiper
    faux_module.SynthesisConfig = faux_config
    with mock.patch.dict(sys.modules, {"piper": faux_module}):
        quest_reader.PiperEngine({"dialogue": "x", "narration": "y"}, 1.25, 0)

    # Un débit de 1.25 doit raccourcir la durée, non l'allonger.
    assert rendus["length_scale"] == pytest.approx(0.8)


def filtre(mots):
    """Applique « keep_word » à une suite de (mot, confiance), comme le
    fait « read_words » sur la sortie d'image_to_data."""
    return clean(" ".join(mot for mot, conf in mots if keep_word(mot, conf)))


@pytest.mark.parametrize(
    "mots, attendu",
    [
        (
            [("2E", 40), ("Qu'est-ce", 90), ("qu'il", 90), ("fait", 90),
             ("chaud", 90), ("ici…", 90)],
            "Qu'est-ce qu'il fait chaud ici…",
        ),
        (
            [("Qu'est-ce", 90), ("qu'il", 90), ("fait", 90), ("chaud", 90),
             ("ici…", 90), ("x.", 40)],
            "Qu'est-ce qu'il fait chaud ici…",
        ),
        (
            [("3A", 40), ("Bonjour", 90), ("aventurier.", 90)],
            "Bonjour aventurier.",
        ),
        (
            [("Bonjour", 90), ("aventurier.", 90), ("e", 43)],
            "Bonjour aventurier.",
        ),
    ],
)
def test_retire_le_bruit_colle_et_minuscule(mots, attendu):
    """Le bruit d'icônes colle chiffres et capitales (« 2E »), ou traîne
    une minuscule isolée en queue (« x. »)."""
    assert filtre(mots) == attendu


def test_deux_lectures_bruitees_restent_un_seul_dialogue():
    """Le bruit ne doit pas faire relire : c'est ce qui doublait la lecture."""
    phrase = [("Qu'est-ce", 90), ("qu'il", 90), ("fait", 90), ("chaud", 90),
              ("ici…", 90)]
    assert same_dialog(
        filtre([("2E", 40)] + phrase),
        filtre(phrase + [("x.", 40)]),
    )


@pytest.mark.parametrize(
    "sample", [CLIQUETIS, ENROLEMENT], ids=["cliquetis", "enrolement"]
)
def test_lit_les_bulles_collees_aux_reponses(sample):
    """Bulle et réponses se touchent : la morphologie les fond en un bloc.

    Ces deux captures n'étaient pas détectées du tout, faute de trouver la
    paire dialogue/réponses que la détection exigeait.
    """
    assert clean(find_dialog(load(sample))) == sample["expected"]


@pytest.mark.parametrize(
    "bruit",
    [
        [],
        [(115, "x _")],
        [(115, "Â 3 Ë x")],
    ],
)
def test_drop_replies_retire_les_reponses_du_joueur(bruit):
    """Bloc fusionné : les choix du joueur suivent le dialogue à l'OCR.

    Ils ne se reconnaissent plus à leur infinitif — ce critère effaçait de
    vraies phrases — mais au large blanc qui les sépare du dialogue. Les
    fragments d'icônes restés sur la dernière ligne du dialogue ne doivent
    pas empêcher la coupure.
    """
    mots = mots_places(
        [(95, "Je te conseille de t'enrôler.")]
        + bruit
        + [(211, "Prendre le temps d'y réfléchir."),
           (251, "L'interroger à propos de l'édit.")]
    )
    assert texte_de(drop_replies(mots)) == "Je te conseille de t'enrôler."


@pytest.mark.parametrize(
    "bruit, article",
    [
        ([], "L'"),
        ([(115, "x _")], "L'"),
        ([(115, "Â 3 Ë x")], ""),
        ([(115, "Â 3 Ë x")], "L'"),
    ],
)
def test_drop_replies_tolere_le_bruit_et_la_capitale_perdue(bruit, article):
    """Vu en jeu : fragments accentués avant le choix, article amputé.

    L'OCR lit « L'interroger » sans son article. Le critère grammatical
    exigeait une capitale initiale et laissait alors passer le choix ; la
    géométrie, elle, ne dépend pas de la façon dont le choix est écrit.
    """
    mots = mots_places(
        [(95, "Elles serviront à entraîner les bras cassés.")]
        + bruit
        + [(211, "Prendre le temps d'y réfléchir."),
           (251, f"{article}interroger à propos de l'édit."),
           (303, "p")]
    )
    assert texte_de(drop_replies(mots)) == "Elles serviront à entraîner les bras cassés."


@pytest.mark.parametrize(
    "fichier", ["interface_hdv.png", "interface_hdv_liste.png"]
)
def test_ignore_les_panneaux_d_interface(fichier):
    """L'hôtel des ventes ne doit pas être lu.

    Accepter un bloc sans réponses appariées, pour rattraper les bulles
    soudées à leurs choix, laissait aussi passer les panneaux d'interface :
    « Rechercher », « Toutes catégories » étaient énoncés. Une bulle reste
    plus large que haute ; un panneau s'étire vers le bas.
    """
    frame = cv2.imread(str(FIXTURES / fichier))
    assert frame is not None, f"fixture illisible : {fichier}"
    assert find_dialog(frame) is None


@pytest.mark.parametrize(
    "mots, attendu",
    [
        (["Bonjour", "à", "toi,", "aventurier."], True),
        (["FILTRES", "ÉTABLE", "ENCLOS", "ACCOUPLEMENT"], False),
        (["Rechercher", "Niveau", "Toutes", "catégories"], False),
        ([], False),
    ],
)
def test_distingue_un_dialogue_d_un_panneau(mots, attendu):
    """Un panneau aligne des étiquettes, un dialogue enchaîne des phrases.

    La géométrie ne les séparait pas : le panneau des enclos affiche le
    même rapport largeur/hauteur qu'une bulle soudée à ses réponses.
    """
    assert reads_like_dialogue([{"text": mot} for mot in mots]) is attendu


def test_garde_l_exclamation_finale():
    """« Bienvenue ! » était amputé de sa dernière phrase.

    Le français détache « ! » du mot : l'OCR le rend comme un mot à part,
    que le filtre de bruit écartait faute de voyelle. La phrase n'étant
    alors plus close, le nettoyage de queue emportait « Bienvenue » avec.
    """
    assert clean(find_dialog(load(KLAKO))) == KLAKO["expected"]


@pytest.mark.parametrize("signe", ["!", "?", "…", "!!"])
def test_la_ponctuation_forte_survit_au_filtre(signe):
    """Elle porte l'intonation : c'est l'objet même de la lecture."""
    assert keep_word(signe, 90) is True


@pytest.mark.xfail(
    reason="Bug de segmentation connu : la bulle et le bloc de réponses se "
    "touchent, la morphologie les soude en un seul contour, et l'appariement "
    "dialogue/réponses ne trouve plus sa paire. Six pistes de réglage "
    "explorées et écartées (hauteur, écart interne, kernel, is_reply_block sur "
    "moitiés, liseré, cartouche) : aucun signal scalaire ne sépare un dialogue "
    "fusionné du chat ou d'un panneau, le thème s'appliquant à toutes les "
    "fenêtres. Le fix vise à re-segmenter finement pour retrouver deux "
    "contours et rendre l'appariement — qui marche partout ailleurs.",
    strict=True,
)
def test_lit_un_dialogue_fondu_a_ses_reponses():
    """Bulle et réponses soudées en un contour : le dialogue doit rester lu.

    Relevé en jeu chez Roukerol de Nerouz : le dialogue n'était pas lu du tout.
    """
    assert clean(find_dialog(load(ROUKEROL))) == ROUKEROL["expected"]


def test_xtts_pose_la_rustine_isin_mps_friendly():
    """Sans elle, « from TTS.api import TTS » lève sur transformers 5.x.

    Coqui importe « isin_mps_friendly », retiré en 5.x. XTTS ne s'en sert
    pas, mais le module fautif est chargé au passage. Les arguments sont
    passés par mot-clé : la signature compte.
    """
    import quest_reader

    modules, pu = faux_xtts({})
    with mock.patch.dict(sys.modules, modules):
        quest_reader.XttsEngine({"dialogue": "a.wav", "narration": "b.wav"}, 1.0)
        assert hasattr(pu, "isin_mps_friendly")
        elements, test_elements = pu.isin_mps_friendly(
            elements="e", test_elements="t"
        )
    assert (elements, test_elements) == ("e", "t")


def test_xtts_decoupe_par_phrases_et_choisit_la_voix():
    """Le bloc entier d'un coup donnerait le délai reproché à Kokoro.

    Chaque phrase part séparément, et les didascalies prennent le second
    échantillon : XTTS clone deux voix, là où Kokoro n'en a qu'une.
    """
    import quest_reader

    rendus = {}
    modules, _ = faux_xtts(rendus)
    with mock.patch.dict(sys.modules, modules):
        moteur = quest_reader.XttsEngine(
            {"dialogue": "pnj.wav", "narration": "didascalie.wav"}, 1.15
        )
        moteur.speak("Bienvenue ! Approche-toi.", narration=False)
        moteur.speak("se racle la gorge", narration=True)

    appels = rendus["appels"]
    assert [appel["text"] for appel in appels] == [
        "Bienvenue !",
        "Approche-toi.",
        "se racle la gorge",
    ]
    assert [appel["speaker"] for appel in appels] == [
        "pnj.wav",
        "pnj.wav",
        "didascalie.wav",
    ]
    assert {appel["language"] for appel in appels} == {"fr"}
    # « --speed » est un débit et XTTS aussi : aucune inversion, contrairement
    # à Piper qui raisonne en durée.
    assert {appel["speed"] for appel in appels} == {1.15}


def test_xtts_ne_synthetise_pas_un_segment_vide():
    """Le découpage isole parfois une ponctuation seule (« Ah… ! »).

    Sans phonème à concaténer, les moteurs lèvent au lieu de se taire — bug
    déjà rencontré sur Kokoro.
    """
    import quest_reader

    rendus = {}
    modules, _ = faux_xtts(rendus)
    with mock.patch.dict(sys.modules, modules):
        moteur = quest_reader.XttsEngine({"dialogue": "a", "narration": "b"}, 1.0)
        moteur.speak("...", narration=False)

    assert rendus.get("appels", []) == []


def args_xtts(**extra):
    defauts = {"voice_sample": "Damien Black", "narration_sample": "Sofia Hellen"}
    return types.SimpleNamespace(**{**defauts, **extra})


def test_xtts_accepte_une_voix_du_modele():
    """Les voix intégrées se désignent par leur nom, pas par un fichier.

    Cloner un échantillon reste possible, mais donne un rendu inférieur
    quand la référence est elle-même synthétique.
    """
    import quest_reader

    quest_reader.check_xtts(
        args_xtts(voice_sample="Damien Black", narration_sample="Sofia Hellen")
    )
    assert quest_reader.voice_argument("Damien Black") == {"speaker": "Damien Black"}


def test_xtts_signale_un_wav_introuvable(tmp_path):
    """Un chemin en .wav qui n'existe pas est une faute de frappe."""
    import quest_reader

    with pytest.raises(SystemExit) as sortie:
        quest_reader.check_xtts(
            args_xtts(
                voice_sample=str(tmp_path / "absent.wav"),
                narration_sample="Sofia Hellen",
            )
        )
    assert "introuvable" in str(sortie.value)


def test_xtts_clone_un_wav_existant(tmp_path):
    """Un fichier réel doit passer par le clonage, pas par le nom."""
    import quest_reader

    echantillon = tmp_path / "voix.wav"
    echantillon.write_bytes(b"")
    assert quest_reader.voice_argument(str(echantillon)) == {
        "speaker_wav": str(echantillon)
    }


def test_xtts_refuse_un_echantillon_introuvable(tmp_path):
    """Un chemin fourni mais absent doit se dire, pas se découvrir 83 s plus
    tard au chargement du modèle."""
    import quest_reader

    present = tmp_path / "voix.wav"
    present.write_bytes(b"")
    args = args_xtts(
        voice_sample=str(present), narration_sample=str(tmp_path / "absent.wav")
    )
    with pytest.raises(SystemExit) as sortie:
        quest_reader.check_xtts(args)
    assert "introuvable" in str(sortie.value)


def test_xtts_sans_cuda_explique_et_s_arrete(tmp_path):
    """Sur processeur le ratio serait dix fois pire : injouable."""
    import quest_reader

    echantillon = tmp_path / "voix.wav"
    echantillon.write_bytes(b"")
    args = args_xtts(
        voice_sample=str(echantillon), narration_sample=str(echantillon)
    )
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    with mock.patch.dict(sys.modules, {"torch": torch}):
        with pytest.raises(SystemExit) as sortie:
            quest_reader.check_xtts(args)
    assert "CUDA" in str(sortie.value)


def test_build_engine_route_vers_xtts():
    """Le contrôle vit dans « main », pas dans le moteur : « sys.exit »
    depuis le fil « Speaker » est avalé en silence par threading."""
    import quest_reader

    rendus = {}
    modules, _ = faux_xtts(rendus)
    args = types.SimpleNamespace(
        engine="xtts", speed=1.15, voice_sample="pnj.wav", narration_sample="dida.wav"
    )
    with mock.patch.dict(sys.modules, modules):
        moteur = quest_reader.build_engine(args)

    assert isinstance(moteur, quest_reader.XttsEngine)
    assert rendus["device"] == "cuda"
    assert rendus["model"] == "tts_models/multilingual/multi-dataset/xtts_v2"


def test_xtts_absent_du_venv_dit_comment_l_installer(tmp_path):
    """Cas courant, pas accidentel : XTTS pèse ~3 Go et vit hors du venv du
    projet. Sans ce garde-fou, l'utilisateur reçoit un ModuleNotFoundError nu.
    """
    import quest_reader

    echantillon = tmp_path / "voix.wav"
    echantillon.write_bytes(b"")
    args = args_xtts(
        voice_sample=str(echantillon), narration_sample=str(echantillon)
    )
    # Simule un venv sans torch, quel que soit celui qui exécute les tests.
    with mock.patch.dict(sys.modules, {"torch": None}):
        with pytest.raises(SystemExit) as sortie:
            quest_reader.check_xtts(args)
    assert "pip install" in str(sortie.value)
