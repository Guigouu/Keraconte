"""Tests de la boucle de lecture (keraconte.reader).

Pilotent un « Reader » nu — moteur et capture doublés — image par image, pour
vérifier l'accumulation des variantes, la coupure et la relecture.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from keraconte import Reader  # noqa: E402
from keraconte.speed import Vitesse  # noqa: E402
from keraconte.text import clean  # noqa: E402
from unittest import mock  # noqa: E402

from tests.helpers import (  # noqa: E402
    BWORKIDAIS,
    HERCULE,
    HERCULE_PERMUTE,
    erase,
    images,
    lecteur_nu,
    load,
)


def test_lecteur_nu_expose_une_vitesse():
    """Le Reader porte une Vitesse partagée, transmise au moteur puis à
    l'overlay. Le lecteur nu doit l'exposer comme le vrai « __init__ »."""
    assert isinstance(lecteur_nu().vitesse, Vitesse)


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


CUISINE = (
    "Ne sois pas autant pressé ! Des travaux pour aménager des cavernes "
    "étaient en cours non loin du lieu du cambriolage. Après avoir discuté "
    "avec Hercule Poivrot, tu iras interroger le chef de chantier. Je l'ai "
    "convoqué en cuisine."
)
CUISINE_REPONSES = CUISINE + " ! ? 5 ? Suivre les ordres."


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
    """Une image absente isolée ne coupe pas : le seuil est de deux."""
    reader = lecteur_nu(last_text="Bonjour, aventurier.")
    images(reader, [None])
    reader.speaker.silence.assert_not_called()


def test_deux_images_absentes_coupent():
    """Le seuil de coupure est de deux images sans bulle."""
    reader = lecteur_nu(last_text="Bonjour, aventurier.")
    images(reader, [None, None])
    reader.speaker.silence.assert_called_once()


def test_la_bulle_fermee_coupe_la_dictee():
    """Après assez d'images sans bulle, la voix s'arrête et la file se vide."""
    reader = lecteur_nu(last_text="Bonjour, aventurier.")
    images(reader, [None] * 2)

    reader.speaker.silence.assert_called_once()
    # Le texte reste en mémoire : deux images sans lecture ne prouvent pas
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
    trou = [None] * 2
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
    images(reader, [texte] * 2 + [None] * 2)
    reader.speaker.silence.assert_called_once()


def test_la_fermeture_coupe_malgre_le_chat_et_la_barre():
    """Sur une vraie capture, fermer le dialogue coupe la voix.

    Relevé en jeu : la voix allait jusqu'au bout de la réplique quand on
    fermait la fenêtre. Le chat et la barre de sorts, bleus comme une bulle,
    étaient vus par « find_bubbles » : « une bulle existe » restait donc vrai
    en permanence et la coupure ne partait jamais. On ne coupe désormais que
    si LA bulle lue a quitté sa place — ce que ces panneaux ne font pas.

    Ce test tourne sur la capture pleine (chat + barre présents), là où un
    crop ne verrait aucun panneau et laisserait le bug passer.
    """
    reader = lecteur_nu()
    ouvert = load(BWORKIDAIS)
    ferme = erase(erase(ouvert, BWORKIDAIS["dialogue"]), BWORKIDAIS["replies"])

    # Image 1 : le dialogue est lu, sa place est retenue.
    reader.handle(ouvert)
    assert reader.last_box is not None
    # Images 2-3 : fenêtre fermée, OCR muet, mais chat et barre subsistent.
    with mock.patch(
        "keraconte.reader.find_dialog_box", return_value=(None, None)
    ):
        reader.handle(ferme)
        reader.handle(ferme)
    reader.speaker.silence.assert_called_once()


def test_un_ocr_muet_sur_la_vraie_bulle_ne_coupe_pas():
    """Le pendant du test ci-dessus : bulle toujours là, OCR muet, pas de coupe.

    C'est le cas que la garde per-boîte doit épargner : la bulle occupe encore
    sa place (l'OCR a seulement cligné), la voix ne doit pas s'arrêter.
    """
    reader = lecteur_nu()
    ouvert = load(BWORKIDAIS)

    reader.handle(ouvert)
    with mock.patch(
        "keraconte.reader.find_dialog_box", return_value=(None, None)
    ):
        reader.handle(ouvert)
        reader.handle(ouvert)
    reader.speaker.silence.assert_not_called()


def test_la_coupure_oublie_la_place_de_la_bulle():
    """Après coupure, la place mémorisée ne doit plus retenir une coupure.

    Sinon une bulle d'un autre PNJ tombant au même endroit, si l'OCR cligne à
    sa première image, passerait pour l'ancienne et la voix ne se couperait
    pas à sa fermeture.
    """
    reader = lecteur_nu()
    ouvert = load(BWORKIDAIS)
    ferme = erase(erase(ouvert, BWORKIDAIS["dialogue"]), BWORKIDAIS["replies"])

    reader.handle(ouvert)
    with mock.patch(
        "keraconte.reader.find_dialog_box", return_value=(None, None)
    ):
        reader.handle(ferme)
        reader.handle(ferme)  # coupure ici
    assert reader.last_box is None


def test_rouvrir_le_dialogue_plus_tard_le_relit():
    """La tolérance ci-dessus ne doit pas rendre un PNJ définitivement muet."""
    reader = lecteur_nu()
    texte = "Tu ne vois pas que je suis en patrouille ?"
    lus = images(reader, [texte] * 2)
    # Le joueur revient bien après le délai de relecture.
    reader.last_seen -= reader.args.repeat_after + 1
    lus = images(reader, [None] * 2 + [texte] * 2)
    assert len(lus) == 2


AFFREUDITE = (
    "Je ne trouve pas de bijou digne de ma beauté. Ici, il y a plein de "
    "pierres précieuses arrachées aux entrailles de la terre, mais moi ce qui "
    "me plairait, ce serait un bijou en nacre serti de perles parfaites."
)


def test_un_texte_vu_une_seule_fois_est_lu_avant_d_etre_jete():
    """Vu en jeu (Affreudite) : le dialogue n'était JAMAIS lu.

    Sur un fond très contrasté, « find_bubbles » ne dégage la bulle qu'une
    image sur dix : le texte complet est vu une fois, mis en attente pour
    confirmation… et la confirmation ne vient jamais. La bulle disparaît, et
    « pending » était vidé sans avoir jamais été dit.

    Ici le choix n'est plus « lire tôt ou lire juste » mais « lire ou ne rien
    lire » : à l'instant où l'on jetterait le texte, on le lit.
    """
    reader = lecteur_nu()
    lus = images(reader, [AFFREUDITE] + [None] * 2)
    assert lus == [clean(AFFREUDITE)]


def test_le_rattrapage_ne_dit_pas_un_texte_manifestement_tronque():
    """Le rattrapage ne doit pas ressusciter le bug du dialogue amputé.

    Un fragment sans ponctuation finale est une lecture d'OCR en chemin
    (mémoire « texte-progressif ») : le taire reste le bon choix.
    """
    reader = lecteur_nu()
    lus = images(reader, ["Un dresseur a craché le morceau il a indiqué"] + [None] * 2)
    assert lus == []


def test_le_rattrapage_ne_double_pas_un_dialogue_deja_lu():
    """Le cas normal (deux images concordantes) ne doit pas être relu à la coupure."""
    reader = lecteur_nu()
    lus = images(reader, [AFFREUDITE] * 2 + [None] * 2)
    assert lus == [clean(AFFREUDITE)]


def test_la_coupure_n_est_ordonnee_qu_une_fois():
    """Rester devant un écran sans bulle ne doit pas marteler « silence »."""
    reader = lecteur_nu()
    images(reader, [None] * 8)
    reader.speaker.silence.assert_called_once()


def test_une_bulle_qui_revient_annule_le_decompte():
    """Une image sans bulle puis une avec : le décompte repart de zéro."""
    reader = lecteur_nu()
    images(reader, [None] + ["Me revoilà."] + [None])
    reader.speaker.silence.assert_not_called()


def test_arrete_ignore_les_images():
    """Stoppé, le lecteur n'analyse plus : aucun dialogue n'est dit."""
    from keraconte.playback import player_state

    reader = lecteur_nu()
    player_state.stop()
    try:
        lus = images(reader, ["Un dialogue qui ne doit pas être lu."] * 3)
        assert lus == []
    finally:
        player_state.reprendre()


def test_en_pause_continue_d_analyser():
    """En pause, l'analyse tourne : un nouveau dialogue est bien détecté
    (c'est lui qui, via Speaker.say, lèvera la pause)."""
    from keraconte.playback import player_state

    reader = lecteur_nu()
    player_state.pause()
    try:
        lus = images(reader, ["Nouveau dialogue à l'écran."] * 3)
        assert lus == ["Nouveau dialogue à l'écran."]
    finally:
        player_state.reprendre()
