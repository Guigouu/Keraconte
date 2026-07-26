"""Tests de l'objet Vitesse partagé (quest_reader.speed)."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from quest_reader.speed import MAX, MIN, PAS, Vitesse  # noqa: E402


def test_valeur_initiale():
    """La valeur passée est celle qu'on relit, si elle est dans la plage."""
    assert Vitesse(1.22).valeur == pytest.approx(1.22)


def test_augmenter_deplace_d_un_pas():
    vitesse = Vitesse(1.0)
    vitesse.augmenter()
    assert vitesse.valeur == pytest.approx(1.0 + PAS)


def test_diminuer_deplace_d_un_pas():
    vitesse = Vitesse(1.0)
    vitesse.diminuer()
    assert vitesse.valeur == pytest.approx(1.0 - PAS)


def test_augmenter_ne_franchit_jamais_le_maximum():
    vitesse = Vitesse(MAX)
    vitesse.augmenter()
    assert vitesse.valeur == pytest.approx(MAX)


def test_diminuer_ne_franchit_jamais_le_minimum():
    vitesse = Vitesse(MIN)
    vitesse.diminuer()
    assert vitesse.valeur == pytest.approx(MIN)


def test_au_maximum_vrai_a_la_borne_haute():
    assert Vitesse(MAX).au_maximum() is True
    assert Vitesse(MAX).au_minimum() is False


def test_au_minimum_vrai_a_la_borne_basse():
    assert Vitesse(MIN).au_minimum() is True
    assert Vitesse(MIN).au_maximum() is False


def test_pas_de_derive_flottante():
    """Dix hausses puis dix baisses reviennent EXACTEMENT au départ.

    Sans arrondi à chaque pas, l'addition répétée de 0.1 dériverait et le
    retour ne coïnciderait plus avec la valeur initiale.
    """
    vitesse = Vitesse(1.0)
    for _ in range(10):
        vitesse.augmenter()
    for _ in range(10):
        vitesse.diminuer()
    assert vitesse.valeur == 1.0


def test_valeur_initiale_bornee_hors_plage():
    """Une valeur initiale hors [MIN, MAX] est ramenée dans la plage."""
    assert Vitesse(10.0).valeur == pytest.approx(MAX)
    assert Vitesse(0.0).valeur == pytest.approx(MIN)
