"""Tests de la boucle de lecture (quest_reader.reader).

Pilotent un « Reader » nu — moteur et capture doublés — image par image, pour
vérifier l'accumulation des variantes, la coupure et la relecture.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader import Reader  # noqa: E402
from quest_reader.text import clean  # noqa: E402
from tests.helpers import (  # noqa: E402
    HERCULE,
    HERCULE_PERMUTE,
    images,
    lecteur_nu,
)


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


def test_rouvrir_le_dialogue_plus_tard_le_relit():
    """La tolérance ci-dessus ne doit pas rendre un PNJ définitivement muet."""
    reader = lecteur_nu()
    texte = "Tu ne vois pas que je suis en patrouille ?"
    lus = images(reader, [texte] * 2)
    # Le joueur revient bien après le délai de relecture.
    reader.last_seen -= reader.args.repeat_after + 1
    lus = images(reader, [None] * 2 + [texte] * 2)
    assert len(lus) == 2


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
