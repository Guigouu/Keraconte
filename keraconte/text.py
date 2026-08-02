"""Nettoyage et comparaison du texte lu par l'OCR (feuille : aucun import du
package). Recolle les lignes, écarte les parasites, reconnaît deux lectures
d'une même réplique, prépare le texte pour la synthèse.
"""

import difflib
import re

# Réécritures appliquées avant la synthèse seulement. Sans voyelle, les
# moteurs épellent l'onomatopée lettre à lettre.
PRONUNCIATION = [(r"\bPs+t\b", "Pssit")]


def clean(text):
    """Recolle les lignes et retire les parasites laissés par les icônes."""
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()

    # Plus aucune regex de bruit ici : le tri se fait au mot, dans
    # « keep_word », où la confiance de l'OCR est encore disponible.
    # Énumérer les formes du bruit (« E x », « 2E », « CON . ») ne
    # convergeait pas — chaque partie en révélait de nouvelles — et
    # corriger une forme en cassait une autre.

    # La fin suit un vrai mot ou ferme une didascalie ; une ponctuation
    # isolée en queue ("\\ ; .") relève encore du bruit.
    # Le français place une espace avant « ? » et « ! » : on l'accepte.
    ends = list(re.finditer(r"[A-Za-zÀ-ÿŒœ0-9’'](?:\s?[.!?…]+|\s*\*)", text))
    if ends:
        text = text[: ends[-1].end()]
    return text.strip()


def strip_choices(text):
    """Recolle les lignes, sans plus retirer aucune phrase.

    Les réponses du joueur se reconnaissaient à leur verbe à l'infinitif.
    Ce critère grammatical effaçait de vraies phrases de PNJ : « Rester ici
    serait dangereux. » disparaissait sans trace. Le retrait se fait
    désormais sur la géométrie, dans « drop_replies », où les boîtes des
    mots sont encore connues — un texte seul ne peut pas les distinguer.
    """
    return re.sub(r"\s+", " ", text).strip()


def fingerprint(text):
    """Empreinte des lettres et des chiffres, sans casse ni ponctuation.

    Les chiffres comptent : « rapporte 5 peaux » et « rapporte 6 peaux »
    sont deux quêtes différentes, et les confondre en tairait une.
    """
    return re.sub(r"[^a-zà-ÿœ0-9]", "", text.lower())


# Deux lectures d'une même bulle diffèrent de quelques lettres au plus.
# Mesuré : « doué » lu « doub », « grand » lu « grancl ». Deux répliques
# distinctes, elles, ne se ressemblent pas à ce point.
SAME_DIALOG_RATIO = 0.9
# Au-delà, un chiffre qui bouge est du bruit d'OCR, pas une quantité de
# quête. Mesuré sur les cas connus : quantités à 16 et 31 caractères
# (« Il m'en faut 10. », « Va chercher 5 peaux de bouftou. »), bruit à 76
# et 315 (Dyaul, Brâkmar). Le seuil est posé au milieu de cet écart.
NUMBERS_DECIDE_BELOW = 50
# Écart de longueur en deçà duquel deux lectures du même dialogue sont
# tenues pour aussi complètes l'une que l'autre. Mesuré : deux variantes ne
# différant que par le bruit d'OCR s'écartent de 2 caractères, une phrase
# entière manquante en retire 57.
NOISE_SLACK = 10
# Écart de vocabulaire en deçà duquel deux lectures sont la même réplique.
# Mesuré sur les captures : variantes d'un même dialogue de 0,00 à 0,31
# (permutation de lignes comprise), dialogues distincts de 1,86 à 4,11.
SAME_WORDS_GAP = 0.6


def clearest(*variants):
    """Choisit la meilleure lecture parmi plusieurs images du même texte.

    La complétude prime : l'OCR rend parfois une variante tronquée (dernière
    ligne ratée) avant la complète — le jeu, lui, affiche la bulle d'un coup.
    Une variante plus courte est donc une phrase mal lue, pas une phrase moins
    avancée. Trier d'abord sur la propreté faisait préférer « ...apaiser le
    molosse. » à la réplique entière, dont la fin n'était alors jamais dite.

    À longueur voisine, on départage sur le bruit : l'OCR rend « longtemps »
    tantôt juste, tantôt « —L|nngremps », et ces caractères-là n'existent pas
    dans du français écrit.
    """

    def damage(text):
        return sum(1 for sign in text if not re.match(r"[\w\s'’!?.,;:…-]", sign))

    # La médiane, et non le maximum : une variante qui dépasse nettement les
    # autres porte un bloc de réponses que « drop_replies » a laissé passer,
    # et la prendre pour référence faisait dire « Je l'ai convoqué en cuisine.
    # Suivre les ordres. » On ne peut pas la reconnaître à son texte — c'est
    # tout l'objet de « drop_replies » —, mais on peut refuser de la suivre
    # quand les autres lectures s'accordent sur plus court.
    lengths = sorted(len(text) for text in variants)
    typical = lengths[len(lengths) // 2]
    complete = [text for text in variants if abs(len(text) - typical) <= NOISE_SLACK]
    return min(complete or variants, key=damage)


def word_gap(first, second):
    """Mesure l'écart de vocabulaire entre deux lectures, relatif à la plus courte.

    Insensible à l'ordre des mots et à la troncature, là où la comparaison de
    séquence trébuche sur les deux. Les mots de moins de trois lettres sont
    ignorés : l'OCR sème des « À » et des « i » en marge du texte.
    """

    def vocabulary(text):
        return {word for word in re.findall(r"[\w’']{3,}", text.lower())}

    left, right = vocabulary(first), vocabulary(second)
    if not left or not right:
        return 0.0 if left == right else float("inf")
    return len(left ^ right) / min(len(left), len(right))


def same_dialog(first, second):
    """Ces deux textes sont-ils la même réplique, au bruit d'OCR près ?

    Une seule lettre instable suffit à changer un hash exact, et le dialogue
    était alors relu en entier. On compare donc par similarité.
    """
    # Un nombre qui change distingue deux quêtes (« 5 peaux » puis « 6 »),
    # mais pèse trop peu dans le ratio pour s'y voir. Le garde ne vaut donc
    # que sur des textes courts, où le nombre porte vraiment la différence.
    #
    # Sur une longue réplique, un chiffre qui bouge est du bruit d'OCR : vu
    # en jeu sur le dialogue de Brâkmar, « celui qui 4 oserait » à une image
    # et « 2 L'avantage » à la suivante, pour 0,99 de concordance par
    # ailleurs. S'y fier faisait relire les six phrases en entier.
    numbers, others = re.findall(r"\d+", first), re.findall(r"\d+", second)
    if numbers != others and max(len(first), len(second)) <= NUMBERS_DECIDE_BELOW:
        return False
    left, right = fingerprint(first), fingerprint(second)
    if not left or not right:
        return left == right
    # L'OCR rend le même dialogue de plusieurs façons : tronqué quand Dofus
    # est encore en train de l'écrire, ou lignes permutées quand l'image est
    # saisie pendant un rafraîchissement. Le ratio de séquence ne survit ni à
    # l'un (0,85) ni à l'autre (0,74), et la réplique repartait en lecture.
    #
    # Le vocabulaire, lui, tient : mesuré sur les captures, les variantes d'un
    # même dialogue s'écartent de 0,00 à 0,31, deux dialogues distincts de
    # 1,86 à 4,11. Aucune fixation d'ordre ne franchit cet écart.
    if word_gap(first, second) <= SAME_WORDS_GAP:
        return True
    return difflib.SequenceMatcher(None, left, right).ratio() >= SAME_DIALOG_RATIO


def speakable(text):
    """Ce texte a-t-il de quoi être prononcé ?

    Sans lettre ni chiffre, un moteur ne produit aucun phonème : Kokoro
    concatène alors une liste vide et lève « need at least one array to
    concatenate ». Même définition du contenu que « fingerprint ».
    """
    return bool(re.search(r"[a-zà-ÿœ0-9]", text.lower()))


def split_narration(text):
    """Découpe le texte en segments (est_narration, contenu).

    Les jeux notent les actions entre astérisques — « * se racle la gorge * »
    — et on les prononce avec une autre voix que la parole du PNJ.
    """
    segments = []
    for index, part in enumerate(re.split(r"\*([^*]+)\*", text)):
        part = part.strip(" *")
        # Entre deux didascalies accolées, il ne reste parfois qu'un trait
        # d'union : rien à dire, et le moteur s'y casse.
        if speakable(part):
            segments.append((index % 2 == 1, part))
    return segments


def pronounce(text):
    """Réécrit ce qui se prononce mal, sans toucher au texte affiché.

    Les synthétiseurs épellent les onomatopées dépourvues de voyelle :
    « Pssst » sort en « p-s-s-s-t ». Ajouter une voyelle suffit à les
    faire prononcer, en gardant la sonorité sifflante.
    """
    for pattern, replacement in PRONUNCIATION:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def split_sentences(text):
    """Découpe en phrases, ponctuation comprise."""
    parts = re.findall(r"[^.!?…]+[.!?…]*", text)
    return [part.strip() for part in parts if part.strip()]
