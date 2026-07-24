"""Détection et OCR de la bulle de dialogue (dépend de text). Isole la bulle
dans l'image, en lit le texte, écarte le bruit d'icônes et les réponses du
joueur.
"""

import re

import cv2
import numpy as np
import pytesseract
from PIL import Image

from quest_reader.text import clean

# Deux habillages de bulle coexistent selon le thème choisi dans le jeu.
#
# Le thème sombre d'origine peint un aplat gris neutre, que le décor coloré
# de Dofus ne sait pas imiter : l'écart entre canaux RVB suffit à l'isoler.
MAX_CHANNEL_SPREAD = 12
VALUE_MIN, VALUE_MAX = 18, 75
# Le thème bleu, lui, est trop coloré pour ce critère — son écart monte à 23
# quand le bois du décor est à 47. C'est alors la teinte qui tranche, et elle
# tranche mieux : mesuré sur une capture de forge, bulle et réponses à 117,
# tout le décor sous 28. Aucune fuite dans les zones témoins.
BLUE_HUE_MIN, BLUE_HUE_MAX = 100, 135
BLUE_VALUE_MIN, BLUE_VALUE_MAX = 30, 90

# CLOSE doit rester étroit : à 5 et au-delà, il soude la bulle au bloc de
# réponses quand l'écart est serré, et l'appariement ne trouve plus la
# paire qu'il exige — le dialogue passe alors inaperçu.
OPEN_KERNEL = np.ones((9, 9), np.uint8)
CLOSE_KERNEL = np.ones((3, 3), np.uint8)

# Au-delà, un bloc est trop haut pour un simple panneau : il porte le
# dialogue et ses réponses soudés. Mesuré à 664 px sur une capture où les
# deux se touchent, contre 218 px pour une bulle seule.
MERGED_MIN_HEIGHT = 400

# Un sous-contour issu de la re-segmentation n'est retenu que s'il fait au
# moins cette fraction de la largeur du bloc et de sa hauteur : en deçà,
# c'est une écharde de masque, pas une bulle ni un bloc de réponses. En
# fractions du bloc, jamais en pixels : la résolution ne doit pas compter.
SUB_MIN_WIDTH_RATIO = 0.4
SUB_MIN_HEIGHT_RATIO = 0.06

# Accepter un bloc sans réponses appariées ouvre la porte aux panneaux de
# l'interface, isolés eux aussi : l'hôtel des ventes et les enclos se
# faisaient lire. Un dialogue est fait de phrases, un panneau d'étiquettes
# (« FILTRES », « ÉTABLE ») : la ponctuation les sépare nettement. Mesuré
# sur les mots sûrs — 15 à 50 % dans les bulles, 1 à 3 % dans les panneaux.
# La géométrie, elle, ne les séparait pas : un panneau d'enclos affiche le
# même rapport largeur/hauteur qu'une bulle soudée à ses réponses.
MIN_PUNCTUATION_RATIO = 0.08

MIN_AREA = 40000
MIN_WIDTH = 300
MIN_CHARS = 20

# Le texte de dialogue est blanc sur gris. Mesuré : 2.9 % dans une vraie
# bulle contre 0.1 % pour un bloc d'interface sans texte.
MIN_WHITE_RATIO = 0.008
MAX_WHITE_RATIO = 0.15

# Écart vertical entre la bulle et le bloc de réponses. Mesuré à -16 px :
# les deux blocs se touchent, avec un léger recouvrement.
MAX_REPLY_GAP = 160
MAX_REPLY_OVERLAP = 40
ALIGN_TOLERANCE = 60

# Bordure ignorée à l'OCR, pour écarter les icônes des coins.
MARGIN = 34

# Seuils du tri des mots, relevés sur les fixtures via image_to_data.
# Le bruit qui survit au test de structure sort entre 24 et 50 de confiance
# (« PE » 24, « E » 36, « e » 43, « A » 44, « : » 50) ; les vrais mots courts
# sont bien au-dessus (« Si » 83, « tu » 83, « as » 91, « à » 96). Le seuil
# tient dans cet écart, sans le serrer : l'OCR fait varier ces scores d'une
# image à l'autre.
MIN_WORD_CONFIDENCE = 60
# Les vrais mots mal notés sont longs (« t'enrôler » 41, « lieux, » 53) :
# c'est leur longueur qui les sauve. Le bruit, lui, tient en trois signes.
MAX_NOISE_LENGTH = 3

# Interligne mesuré dans une bulle : 16 à 20 px. L'écart jusqu'au bloc de
# réponses vaut 95 px sur la capture « enrolement ». Le seuil sépare les deux
# sans les toucher.
MIN_REPLY_LINE_GAP = 40
# Deux mots d'une même ligne diffèrent de quelques pixels en ordonnée : leurs
# lignes de base ne coïncident pas au pixel près (mesuré jusqu'à 4 px).
LINE_TOLERANCE = 10


def bubble_mask(frame):
    """Masque des aplats de bulle, avant la fermeture morphologique.

    Isolé de « find_bubbles » pour être réutilisé tel quel sur un fragment
    d'image : la re-segmentation fine (voir « splits_into_pair ») repart de
    ce masque brut, sans la fermeture qui, elle, soude parfois deux blocs.
    """
    blue, green, red = cv2.split(frame.astype(np.int16))
    spread = np.maximum(np.maximum(blue, green), red) - np.minimum(
        np.minimum(blue, green), red
    )
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue, value = hsv[:, :, 0], hsv[:, :, 2]

    # Les deux thèmes sont reconnus d'un même masque : ils ne se recouvrent
    # pas — un aplat gris n'a pas de teinte bleue franche — donc les unir
    # n'ouvre la porte à aucun décor que l'un ou l'autre laissait dehors.
    neutral = (spread < MAX_CHANNEL_SPREAD) & (value > VALUE_MIN) & (value < VALUE_MAX)
    blueish = (
        (hue >= BLUE_HUE_MIN)
        & (hue <= BLUE_HUE_MAX)
        & (value > BLUE_VALUE_MIN)
        & (value < BLUE_VALUE_MAX)
    )
    mask = (neutral | blueish).astype(np.uint8) * 255
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, OPEN_KERNEL)


def find_bubbles(frame):
    """Repère les blocs qui ont l'aspect d'une bulle, sans lire leur texte.

    Séparé de « find_dialog » pour distinguer deux situations qu'un simple
    « None » confondait : la bulle a disparu de l'écran, ou elle est bien là
    mais l'OCR n'en a rien tiré. La première doit couper la voix, la seconde
    surtout pas — c'est la même réplique qui continue de s'afficher.
    """
    height, width = frame.shape[:2]
    # La fermeture soude les lignes d'un même bloc ; c'est elle aussi qui,
    # quand bulle et réponses se touchent, les fond en un seul contour.
    # « splits_into_pair » repart du masque d'avant pour les distinguer.
    mask = cv2.morphologyEx(bubble_mask(frame), cv2.MORPH_CLOSE, CLOSE_KERNEL)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < MIN_AREA or w < MIN_WIDTH:
            continue
        # L'interface de droite touche le bord ; le reste (chat compris)
        # est écarté par l'exigence d'un bloc de réponses apparié.
        if x + w > width * 0.99:
            continue
        boxes.append((y, x, w, h))

    boxes.sort()
    return boxes, height


def splits_into_pair(frame, box):
    """Ce bloc unique cache-t-il une bulle soudée à ses réponses ?

    Chez certains PNJ, bulle et réponses se touchent : la fermeture
    morphologique globale les fond en un seul contour, et l'appariement
    dialogue/réponses ne trouve plus sa paire — le dialogue passe inaperçu.
    Un seuil de hauteur ne les rattrape pas : le chat et les panneaux de
    l'interface atteignent la même hauteur sans être des dialogues.

    On repart donc du masque d'avant fermeture, restreint à ce seul bloc :
    sans la fermeture qui les soudait, la bulle et les réponses redeviennent
    deux contours distincts, et l'appariement habituel — le seul signal
    fiable, relationnel — s'applique à nouveau. Un vrai bloc isolé (chat,
    panneau, bulle sans réponses) ne se scinde pas : il n'a pas cette paire.

    L'OCR, lui, continue de lire le bloc entier inchangé : cette
    re-segmentation ne sert qu'à décider s'il existe une paire, jamais à
    recadrer le texte.
    """
    y, x, w, h = box
    region = bubble_mask(frame[y : y + h, x : x + w])
    contours, _ = cv2.findContours(
        region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    parts = []
    for contour in contours:
        cx, cy, cw, ch = cv2.boundingRect(contour)
        # Les échardes de masque sont écartées en proportion du bloc, pour
        # ne dépendre d'aucune résolution.
        if cw < w * SUB_MIN_WIDTH_RATIO or ch < h * SUB_MIN_HEIGHT_RATIO:
            continue
        parts.append((cy, cx, cw, ch))
    parts.sort()
    # L'appariement est celui de « is_reply_block », inchangé : un bloc de
    # réponses aligné, de largeur voisine, juste sous le texte.
    for above_index, above in enumerate(parts):
        if any(is_reply_block(above, below) for below in parts[above_index + 1 :]):
            return True
    return False


def find_dialog(frame):
    """Renvoie le texte de la bulle de dialogue, ou None.

    Le bloc de réponses partage l'aspect de la bulle : on ne garde que le
    bloc le plus haut, qui est toujours le dialogue lui-même.
    """
    boxes, height = find_bubbles(frame)

    # Un dialogue de PNJ est toujours suivi d'un bloc de réponses juste
    # en dessous. Les panneaux d'interface, eux, sont isolés : exiger la
    # paire écarte les faux positifs.
    for index, (y, x, w, h) in enumerate(boxes):
        replies = next(
            (
                other
                for other in boxes[index + 1 :]
                if is_reply_block((y, x, w, h), other)
            ),
            None,
        )
        # Quand les deux blocs se touchent, la fermeture les fond en un seul :
        # la paire manque alors. On la rattrape en re-segmentant finement le
        # bloc, ce qui rend la bulle et les réponses comme deux contours et
        # rétablit l'appariement. La hauteur reste un pré-filtre bon marché,
        # mais roukerol (314 px) passe sous son seuil : la re-segmentation
        # tranche le cas où la hauteur ne suffit pas.
        if replies is None:
            merged = h >= MERGED_MIN_HEIGHT or splits_into_pair(
                frame, (y, x, w, h)
            )
            if not merged:
                continue
        region = frame[y : y + h, x : x + w]
        white = (region > 200).all(2).mean()
        if not MIN_WHITE_RATIO <= white <= MAX_WHITE_RATIO:
            continue
        # Pas de rognage : la boîte est parfois déjà serrée sur le texte,
        # et rogner amputerait le dialogue. Les icônes des coins sortent
        # en mots isolés, qu'on écarte un à un ci-dessous.
        crop = cv2.cvtColor(region, cv2.COLOR_BGR2RGB)
        # image_to_data plutôt que image_to_string : c'est le seul moyen
        # d'obtenir la confiance et la boîte de chaque mot, sur lesquelles
        # reposent le tri du bruit et le repérage des réponses.
        data = pytesseract.image_to_data(
            Image.fromarray(crop), lang="fra", output_type=pytesseract.Output.DICT
        )
        words = read_words(data)
        # Sur un bloc fusionné, l'OCR ramène aussi les réponses du joueur :
        # elles se détachent par un large blanc, pas par leur grammaire.
        if replies is None:
            words = drop_replies(words)
        # Un bloc admis sur sa seule hauteur peut être un panneau de
        # l'interface : sans réponses appariées, rien ne l'a encore écarté.
        if replies is None and not reads_like_dialogue(words):
            continue
        text = clean(" ".join(word["text"] for word in words))
        if len(text) >= MIN_CHARS:
            return text
    return None


def reads_like_dialogue(words):
    """Ces mots forment-ils des phrases, ou une liste d'étiquettes ?

    Les panneaux du jeu (hôtel des ventes, enclos) alignent des libellés
    sans ponctuation — « FILTRES », « ÉTABLE » — là où un dialogue enchaîne
    des phrases. La géométrie ne les distingue pas : certains panneaux ont
    le même rapport largeur/hauteur qu'une bulle soudée à ses réponses.
    """
    if not words:
        return False
    ponctues = sum(
        1 for word in words if any(sign in word["text"] for sign in ".,!?…")
    )
    return ponctues / len(words) >= MIN_PUNCTUATION_RATIO


def read_words(data):
    """Extrait les mots retenus de la sortie d'image_to_data.

    L'ordre de lecture est celui de Tesseract (bloc, paragraphe, ligne, mot)
    et non l'ordonnée brute : les fragments d'icônes forment leurs propres
    blocs, et trier sur « top » entrelacerait leurs lettres avec le texte.
    """
    words = []
    for index, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        if not keep_word(text, int(data["conf"][index])):
            continue
        words.append(
            {
                "text": text,
                "top": int(data["top"][index]),
                "order": (
                    int(data["block_num"][index]),
                    int(data["par_num"][index]),
                    int(data["line_num"][index]),
                    int(data["word_num"][index]),
                ),
            }
        )
    words.sort(key=lambda word: word["order"])
    return words


# Une voyelle, une apostrophe ou un tiret font un mot français plausible.
# L'apostrophe compte : « C' » et « d'y » sont des élisions, pas du bruit.
PLAUSIBLE = re.compile(r"[aeiouyàâäéèêëîïôöùûüÿœæAEIOUYÀÂÄÉÈÊËÎÏÔÖÙÛÜŒÆ’'-]")


def keep_word(text, confidence):
    """Ce mot vient-il du dialogue, ou d'une icône mal lue ?

    Deux signaux croisés, mesurés sur les fixtures : ni l'un ni l'autre ne
    suffit seul. La structure attrape le bruit bien noté (« x » à 95, « R »
    à 93), la confiance attrape le bruit plausible (« PE » 24, « A » 44).
    La position, elle, ne sert à rien : le bruit apparaît aussi en plein
    milieu d'une phrase (« Si ça A3 t'intéresse »).
    """
    text = text.strip()
    if not text:
        return False
    # Un nombre seul est toujours du dialogue : il porte les quantités de
    # quête (« ramène-moi 10 dagues »), et les taire prive le joueur de
    # l'information. Ce test passe avant celui de la structure, qui les
    # rejetterait faute de voyelle.
    if text.isdigit():
        return True
    # Le français détache « ! » et « ? » du mot : l'OCR les rend alors
    # comme un mot à part. Ils portent l'intonation, et les jeter
    # transformait « Bienvenue ! » en « Bienvenue » — puis, la phrase
    # n'étant plus close, le mot disparaissait au nettoyage de queue.
    if all(sign in "!?…" for sign in text):
        return True
    # Mêler chiffres et lettres ne fait jamais un mot français : « A3 »,
    # « 2E », « SN 64 ». Aucune confiance ne rachète cette forme.
    if re.search(r"\d", text) and re.search(r"[^\W\d_]", text):
        return False
    # Sans voyelle, ce n'est pas un mot français — « »/ », « x », « R »,
    # « dn » — sauf une onomatopée, que le jeu écrit justement ainsi :
    # « Pssst » sort à 91 de confiance sur la capture « tokageko ». Le
    # bruit sans voyelle, lui, est court ET mal noté : rejeter sur la
    # seule structure tairait l'onomatopée.
    if not PLAUSIBLE.search(text):
        return len(text) > MAX_NOISE_LENGTH and confidence >= MIN_WORD_CONFIDENCE
    # Reste le bruit structurellement plausible (« PE » 24, « A » 44). Les
    # vrais mots mal notés sont longs (« t'enrôler » 41, « lieux, » 53) :
    # la longueur les sauve.
    return len(text) > MAX_NOISE_LENGTH or confidence >= MIN_WORD_CONFIDENCE


def drop_replies(words):
    """Retire les réponses du joueur d'un bloc fusionné, par géométrie.

    Les reconnaître à leur verbe à l'infinitif effaçait de vraies phrases
    de PNJ (« Rester ici serait dangereux. »). Or les réponses sont
    séparées du dialogue par un blanc bien plus large qu'un interligne :
    16 à 20 px entre deux lignes, 95 px avant le premier choix.
    """
    if not words:
        return words
    # Les mots d'une même ligne ne partagent pas exactement leur ordonnée :
    # on les regroupe par proximité, dans l'ordre où ils apparaissent.
    tops = sorted({word["top"] for word in words})
    lines = [[tops[0]]]
    for top in tops[1:]:
        if top - lines[-1][-1] <= LINE_TOLERANCE:
            lines[-1].append(top)
        else:
            lines.append([top])
    # Le dialogue occupe le haut du bloc : on coupe au premier grand écart.
    for previous, current in zip(lines, lines[1:]):
        if current[0] - previous[-1] >= MIN_REPLY_LINE_GAP:
            return [word for word in words if word["top"] <= previous[-1]]
    return words


def is_reply_block(dialog, candidate):
    """Le bloc candidat est-il la liste de réponses sous ce dialogue ?"""
    dialog_y, dialog_x, dialog_w, dialog_h = dialog
    y, x, w, _ = candidate
    # Les deux blocs se chevauchent parfois de quelques pixels.
    gap = y - (dialog_y + dialog_h)
    if not -MAX_REPLY_OVERLAP <= gap <= MAX_REPLY_GAP:
        return False
    # Les deux blocs partagent le même bord gauche et une largeur voisine.
    if abs(x - dialog_x) > ALIGN_TOLERANCE:
        return False
    return abs(w - dialog_w) <= dialog_w * 0.35
