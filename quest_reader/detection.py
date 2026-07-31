"""Détection et OCR de la bulle de dialogue (dépend de text). Isole la bulle
dans l'image, en lit le texte, écarte le bruit d'icônes et les réponses du
joueur.
"""

import re
import time

import cv2
import numpy as np
import pytesseract
from PIL import Image

from quest_reader.text import clean
from quest_reader.trace import trace as _trace

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
#
# Ces tailles restent en pixels absolus, à dessein. Un noyau modifie ce que
# l'OCR voit sur CHAQUE capture : le rendre relatif à la hauteur changerait
# sa taille effective d'une fixture à l'autre. À 9/1350 puis 3/1350, les
# crops (401 px de haut) recevraient un noyau de 3×3 et 1×1 au lieu de 9×9
# et 3×3 — soit une tout autre segmentation, et un risque de régression OCR
# ailleurs. On préfère l'absolu à ce prix.
OPEN_KERNEL = np.ones((9, 9), np.uint8)
CLOSE_KERNEL = np.ones((3, 3), np.uint8)

# Au-delà, un bloc est trop haut pour un simple panneau : il porte le
# dialogue et ses réponses soudés. Mesuré à 664 px sur une capture où les
# deux se touchent, contre 218 px pour une bulle seule.
#
# Laissé en pixels absolus, à dessein — contrairement aux autres seuils
# géométriques. Le rendre relatif suppose un rapport de forme (hauteur ÷
# largeur), mais la géométrie l'interdit : la bulle soudée d'« enrolement »
# a un rapport de 1,08, plus PLAT que les panneaux d'interface à écarter
# (1,15 à 1,70). Aucun seuil de rapport ne sépare donc les deux. Cette
# valeur absolue ne fonctionne que parce que, à la résolution des fixtures,
# elle tombe dans l'intervalle (314, 664] entre roukerol — rattrapé par la
# re-segmentation — et la bulle soudée. La rendre relative ferait basculer
# un panneau d'enclos (346×399) dans la branche fusionnée, où seul le ratio
# de blanc l'écarte encore, et de justesse (0,0052 contre un seuil de
# 0,008). Un écran d'une autre résolution ne sera pas mieux servi, mais le
# forcer casserait cet équilibre. À revoir avec une capture fusionnée prise
# à une autre définition, pour caler un vrai seuil relatif.
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

# Taille minimale d'un bloc candidat, avant tout appariement : ici aucune
# bulle n'est encore connue, la seule référence d'échelle est l'image. Une
# aire est un produit largeur×hauteur : elle se rapporte donc à l'aire de
# l'image (facteur au carré avec la résolution), la largeur à la largeur.
# Calibrés sur 2560×1350, où l'aire minimale valait 40000 px² et la largeur
# 300 px : 40000 / (2560×1350) et 300 / 2560.
MIN_AREA_RATIO = 40000 / (2560 * 1350)
MIN_WIDTH_RATIO = 300 / 2560
# Plancher de longueur du texte lu. Deux valeurs selon la preuve accumulée :
# sans réponses appariées, le bloc n'est admis que sur sa hauteur ou sa
# ponctuation, et ce plancher écarte le bruit OCR d'un panneau (fragments
# épars). Avec réponses appariées, le signal relationnel a déjà prouvé le
# dialogue : un plancher long y rejetterait à tort les répliques courtes
# (« Zog Zog à toâ. », 14 car.), relevées en jeu chez Gobriel et un Bwork. On
# n'y garde qu'un plancher bas, juste de quoi écarter une écharde de deux ou
# trois lettres.
MIN_CHARS = 20
MIN_CHARS_PAIRED = 6

# Le texte de dialogue est blanc sur gris. Mesuré : 2.9 % dans une vraie
# bulle contre 0.1 % pour un bloc d'interface sans texte.
MIN_WHITE_RATIO = 0.008
MAX_WHITE_RATIO = 0.15

# Écart vertical entre la bulle et le bloc de réponses. Mesuré à -16 px :
# les deux blocs se touchent, avec un léger recouvrement.
#
# Exprimés en fraction de la largeur de la bulle, et non en pixels absolus :
# c'est la seule référence stable d'une résolution à l'autre. La largeur de
# la bulle vaut 555 à 633 px sur toutes les fixtures — pleines captures comme
# crops — quand la largeur d'image, elle, varie du simple au triple. Un écran
# deux fois plus défini donne une bulle deux fois plus large, et ces seuils
# suivent. Calibrés sur une largeur de bulle de référence de 600 px, ils
# reproduisent à moins de 6 % près les valeurs absolues d'origine (160, 40,
# 60) sur les fixtures actuelles.
REF_BUBBLE_WIDTH = 600
MAX_REPLY_GAP_RATIO = 160 / REF_BUBBLE_WIDTH
MAX_REPLY_OVERLAP_RATIO = 40 / REF_BUBBLE_WIDTH
ALIGN_TOLERANCE_RATIO = 60 / REF_BUBBLE_WIDTH

# Tolérance pour reconnaître « la même boîte » d'une image à l'autre : une
# bulle dont l'OCR cligne reste au même endroit, à quelques pixels de gigue
# de contour près. En fraction des dimensions de la boîte, jamais en pixels :
# la gigue suit la taille de la bulle, donc la résolution.
SAME_BOX_TOLERANCE = 0.2

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
#
# Ces deux seuils restent en pixels absolus, à dessein. « drop_replies »
# travaille sur des ordonnées de mots, sans l'image ni le bloc sous la main :
# aucune dimension de référence n'y est disponible. Et surtout, un interligne
# suit la taille de la POLICE — donc la résolution de l'écran — et non la
# hauteur de la bulle : le rapporter à la hauteur du bloc serait la mauvaise
# référence, une bulle haute n'ayant pas un interligne plus large. Deux tests
# appellent « drop_replies » avec des ordonnées écrites en dur ; les rendre
# relatifs changerait sa signature. À caler sur la taille de police le jour
# où on la mesure, pas sur une dimension d'image.
MIN_REPLY_LINE_GAP = 40
# Deux mots d'une même ligne diffèrent de quelques pixels en ordonnée : leurs
# lignes de base ne coïncident pas au pixel près (mesuré jusqu'à 4 px).
LINE_TOLERANCE = 10
# Le bandeau d'icônes en haut de bulle (⋮, ✕) sort à l'OCR en mots isolés
# posés AU-DESSUS de la première ligne de texte, séparés d'elle par un écart
# bien plus large qu'un interligne. Mesuré chez Bworknroll : écart bandeau→texte
# 48 px pour un interligne de 25 (ratio 1,96), quand un dialogue propre a des
# écarts réguliers (ratio ≤ 1,08 sur enrolement/roukerol). Le seuil se pose au
# milieu. On compare le plus grand écart à la MÉDIANE DES AUTRES : l'inclure
# fausserait la référence par le bruit même qu'on isole.
TOP_CHROME_GAP_RATIO = 1.5
# On ne retire la bande de tête que si elle est minoritaire : au-dessus de
# cette part des mots, le « haut » porte du vrai texte (saut de paragraphe),
# pas des icônes. Chez Bworknroll le bandeau pèse 2 mots sur 40.
MAX_TOP_CHROME_RATIO = 0.3
# En deçà de ce nombre de groupes de lignes, la médiane des écarts n'a pas de
# sens (0 ou 1 autre écart) : on ne peut pas distinguer un bandeau d'un vrai
# interligne, donc on ne retire rien — quitte à laisser passer le bruit.
MIN_LINES_FOR_CHROME = 4


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
    # Seuils de taille rapportés aux dimensions de l'image : une aire à son
    # aire, une largeur à sa largeur, pour suivre la résolution de l'écran.
    min_area = MIN_AREA_RATIO * width * height
    min_width = MIN_WIDTH_RATIO * width
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < min_area or w < min_width:
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
    """Renvoie le texte de la bulle de dialogue, ou None."""
    text, _ = find_dialog_box(frame)
    return text


def find_dialog_box(frame, boxes=None):
    """Renvoie (texte, boîte) de la bulle de dialogue, ou (None, None).

    La boîte — (y, x, w, h) du contour lu — sert au lecteur à savoir, quand
    l'OCR redevient muet, si c'est bien CETTE bulle qui est encore à l'écran
    ou seulement le décor (chat, barre de sorts) : eux n'occupent jamais sa
    place. Sans ce repère, la présence d'un panneau permanent empêchait la
    voix de se couper à la fermeture du dialogue.

    Le bloc de réponses partage l'aspect de la bulle : on ne garde que le
    bloc le plus haut, qui est toujours le dialogue lui-même.

    « boxes » permet de réutiliser une segmentation déjà faite : quand l'image
    n'a pas de texte, le lecteur rappelle « bubble_still_there » sur la même
    image, et « find_bubbles » (morphologie pleine image) tournait deux fois.
    Fourni, on ne re-segmente pas ; laissé à None, on segmente comme avant —
    l'API reste inchangée pour les tests et le chemin « --test ».
    """
    if boxes is None:
        boxes, _ = find_bubbles(frame)
    _ocr_ms = 0.0

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
        # bloc (« splits_into_pair »), ce qui rend la bulle et les réponses
        # comme deux contours et rétablit l'appariement. La hauteur reste un
        # pré-filtre bon marché, mais roukerol (314 px) passe sous son seuil.
        #
        # Deux preuves distinctes admettent un bloc sans réponses appariées, et
        # elles ne se valent PAS. Une paire re-segmentée est une preuve
        # RELATIONNELLE, de même nature que « replies is not None » : le bloc est
        # un dialogue soudé à ses réponses. La seule hauteur, elle, ne prouve
        # rien — un panneau d'interface (hôtel des ventes, 838 px) est tout aussi
        # haut. « paired » garde la trace de ce qui a admis le bloc et commande
        # en aval le saut de « reads_like_dialogue » et le plancher bas.
        #
        # « splits_into_pair » DOIT donc tourner inconditionnellement ici, même
        # quand la hauteur suffirait déjà : le court-circuiter derrière
        # « h >= MERGED » (comme le faisait l'ancien
        # « h >= MERGED or splits_into_pair(...) ») rendrait le correctif
        # inopérant sur un bloc haut ET fusionné (L'Explorancienne à 100 %,
        # h=435). Ne pas « optimiser » cet appel : son coût (bubble_mask sur la
        # seule région) est négligeable face à l'OCR.
        paired = replies is not None
        if replies is None:
            paired = splits_into_pair(frame, (y, x, w, h))
            if not (h >= MERGED_MIN_HEIGHT or paired):
                # Trace par box (silencieuse hors QR_DEBUG) : sur quelle porte le
                # bloc est écarté. Sert à mesurer, sur un flux en jeu, la
                # DISTRIBUTION des chemins d'une image à l'autre — un instantané
                # ne montre pas la variance de la fusion morphologique.
                _trace(
                    f"  box (y={y} x={x} w={w} h={h}) PORTE=pas-de-preuve "
                    f"splits={paired} h>=merged={h >= MERGED_MIN_HEIGHT}"
                )
                continue
        region = frame[y : y + h, x : x + w]
        white = (region > 200).all(2).mean()
        if not MIN_WHITE_RATIO <= white <= MAX_WHITE_RATIO:
            _trace(
                f"  box (y={y} x={x} w={w} h={h}) PORTE=white "
                f"paired={paired} white={white:.4f}"
            )
            continue
        # Pas de rognage : la boîte est parfois déjà serrée sur le texte,
        # et rogner amputerait le dialogue. Les icônes des coins sortent
        # en mots isolés, qu'on écarte un à un ci-dessous.
        crop = cv2.cvtColor(region, cv2.COLOR_BGR2RGB)
        # image_to_data plutôt que image_to_string : c'est le seul moyen
        # d'obtenir la confiance et la boîte de chaque mot, sur lesquelles
        # reposent le tri du bruit et le repérage des réponses.
        # On garde le moteur par défaut « --oem 3 » (legacy + LSTM fusionnés).
        # « --oem 1 » (LSTM seul) est ~35 % plus rapide et rend un texte
        # identique sur une bulle simple, MAIS il place les boîtes par mot
        # autrement : sur un bloc fusionné à ses réponses (cas Roukerol),
        # « drop_replies » — qui sépare dialogue et réponses par le large blanc
        # entre boîtes — coupe alors tout sauf un mot, et le dialogue n'est plus
        # lu du tout. Le gain de vitesse ne vaut pas la perte d'un cas réel ;
        # ré-ajuster « drop_replies » pour OEM 1 serait un chantier à part.
        _t1 = time.perf_counter()
        data = pytesseract.image_to_data(
            Image.fromarray(crop), lang="fra", output_type=pytesseract.Output.DICT
        )
        _ocr_ms += (time.perf_counter() - _t1) * 1000
        words = read_words(data)
        # Sur un bloc fusionné, l'OCR ramène aussi les réponses du joueur :
        # elles se détachent par un large blanc, pas par leur grammaire. On les
        # retire dès qu'il n'y a pas d'appariement D'EMBLÉE (« replies is
        # None ») : même quand « splits_into_pair » a retrouvé la paire, l'OCR a
        # bien lu le bloc entier, réponses comprises.
        if replies is None:
            words = drop_replies(words)
        # Le bandeau d'icônes du haut de bulle (⋮, ✕) sort en « ë - » au-dessus
        # du texte : inconditionnel (la bulle appariée n'est pas passée par
        # « drop_replies »), avant tout calcul en aval qu'il polluerait.
        words = drop_top_chrome(words)
        # « reads_like_dialogue » n'écarte les panneaux d'interface que faute de
        # preuve relationnelle. Or un bloc dont « splits_into_pair » a retrouvé
        # la paire EN A une : le lui imposer rejetait à tort les dialogues
        # narratifs peu ponctués (« L'Explorancienne », 172 car., 2 points sur
        # 28 mots → ratio 0,07 < 0,08). On ne garde donc ce test que pour les
        # blocs admis sur leur SEULE hauteur, où rien n'a encore prouvé le
        # dialogue. Même raisonnement que le plancher apparié plus bas.
        if not paired and not reads_like_dialogue(words):
            _trace(
                f"  box (y={y} x={x} w={w} h={h}) PORTE=like "
                f"mots={len(words)} paired={paired}"
            )
            continue
        text = clean(" ".join(word["text"] for word in words))
        floor = MIN_CHARS_PAIRED if paired else MIN_CHARS
        if len(text) >= floor:
            _trace(f"find_dialog_box: TEXTE | ocr={_ocr_ms:.0f}ms | {len(boxes)} boxe(s)")
            return text, (y, x, w, h)
        _trace(
            f"  box (y={y} x={x} w={w} h={h}) PORTE=floor "
            f"paired={paired} len={len(text)} floor={floor}"
        )
    _trace(f"find_dialog_box: RIEN | ocr={_ocr_ms:.0f}ms | {len(boxes)} boxe(s)")
    return None, None


def bubble_still_there(frame, box, boxes=None):
    """La bulle lue à « box » occupe-t-elle toujours sa place à l'écran ?

    Sert quand l'OCR redevient muet : on ne coupe la voix que si CETTE bulle
    a disparu, pas si un autre bloc (chat, barre de sorts) subsiste — eux ne
    tiennent jamais la place de la bulle. Un simple « une bulle existe » ne
    suffisait pas : ces panneaux permanents comptaient comme une bulle et
    empêchaient toute coupure à la fermeture du dialogue.

    « boxes » réutilise une segmentation déjà faite par « find_dialog_box » sur
    la même image, pour ne pas relancer « find_bubbles » (morphologie pleine
    image) une seconde fois. Laissé à None, on segmente — l'API reste inchangée.
    """
    if box is None:
        return False
    y, x, w, h = box
    if boxes is None:
        boxes, _ = find_bubbles(frame)
    for (cy, cx, cw, ch) in boxes:
        if (
            abs(cx - x) <= w * SAME_BOX_TOLERANCE
            and abs(cy - y) <= h * SAME_BOX_TOLERANCE
            and abs(cw - w) <= w * SAME_BOX_TOLERANCE
            and abs(ch - h) <= h * SAME_BOX_TOLERANCE
        ):
            return True
    return False


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
    # Un nombre est toujours du dialogue : il porte les quantités de quête
    # (« ramène-moi 10 dagues ») et les horaires (« ouverte 24 heures sur
    # 24, »), et les taire prive le joueur de l'information. On accepte le
    # nombre PONCTUÉ, pas seulement « isdigit() » : le français colle la
    # virgule ou le point au chiffre (« 24, », « 24. »), et « 24,».isdigit()
    # est faux — ce qui faisait lire « 24 heures sur 24, » amputé en « sur ».
    # On exige au moins un chiffre et AUCUNE lettre : un fragment mêlant
    # chiffre et lettre (« 2E », « A3 ») reste écarté plus bas. Ce test passe
    # avant celui de la structure, qui rejetterait ces nombres faute de voyelle.
    if re.search(r"\d", text) and not re.search(r"[^\W\d_]", text):
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


def _mediane(valeurs):
    """Médiane d'une liste non vide, sans dépendance externe."""
    triees = sorted(valeurs)
    milieu = len(triees) // 2
    if len(triees) % 2:
        return triees[milieu]
    return (triees[milieu - 1] + triees[milieu]) / 2


def drop_top_chrome(words):
    """Retire le bandeau d'icônes en haut de bulle (⋮, ✕), par géométrie.

    Ces contrôles sortent à l'OCR en mots isolés (« ë », « - ») posés
    AU-DESSUS de la première ligne de texte, avec une confiance qui les fait
    passer « keep_word » — les filtrer au mot est donc impossible. Mais ils
    sont séparés du texte par un écart bien plus large qu'un interligne :
    48 px mesurés chez Bworknroll, contre 25 entre deux lignes.

    On repère cet écart comme le plus grand des débuts de ligne, rapporté à la
    médiane des AUTRES écarts (l'inclure fausserait la référence par le bruit
    qu'on isole), et l'on retire tout ce qui le précède. Deux gardes évitent
    d'amputer un vrai dialogue : il faut assez de lignes pour que la médiane ait
    un sens, et la bande de tête doit rester minoritaire — un « haut » qui porte
    l'essentiel du texte est un saut de paragraphe, pas un bandeau.

    Inconditionnel, APRÈS « drop_replies » : la bulle qui a révélé le bug est
    appariée à ses réponses (« drop_replies » n'a donc jamais tourné dessus), et
    le bandeau coiffe le dialogue quel que soit ce qui le suit.
    """
    if not words:
        return words
    tops = sorted({word["top"] for word in words})
    lines = [[tops[0]]]
    for top in tops[1:]:
        if top - lines[-1][-1] <= LINE_TOLERANCE:
            lines[-1].append(top)
        else:
            lines.append([top])
    if len(lines) < MIN_LINES_FOR_CHROME:
        return words
    starts = [line[0] for line in lines]
    gaps = [second - first for first, second in zip(starts, starts[1:])]
    candidat = max(gaps)
    index = gaps.index(candidat)
    autres = gaps[:index] + gaps[index + 1 :]
    if candidat < TOP_CHROME_GAP_RATIO * _mediane(autres):
        return words
    # La coupe est juste sous le plus grand écart : tout ce qui commence avant
    # la ligne qui le suit est le bandeau.
    seuil = starts[index + 1]
    tete = [word for word in words if word["top"] < seuil]
    if len(tete) > MAX_TOP_CHROME_RATIO * len(words):
        return words  # tête majoritaire : c'est du vrai texte
    return [word for word in words if word["top"] >= seuil]


def is_reply_block(dialog, candidate):
    """Le bloc candidat est-il la liste de réponses sous ce dialogue ?"""
    dialog_y, dialog_x, dialog_w, dialog_h = dialog
    y, x, w, _ = candidate
    # Les seuils suivent la largeur de la bulle : pris en pixels absolus, ils
    # se décalaient dès que la résolution de l'écran changeait.
    max_overlap = dialog_w * MAX_REPLY_OVERLAP_RATIO
    max_gap = dialog_w * MAX_REPLY_GAP_RATIO
    align_tolerance = dialog_w * ALIGN_TOLERANCE_RATIO
    # Les deux blocs se chevauchent parfois de quelques pixels.
    gap = y - (dialog_y + dialog_h)
    if not -max_overlap <= gap <= max_gap:
        return False
    # Les deux blocs partagent le même bord gauche et une largeur voisine.
    if abs(x - dialog_x) > align_tolerance:
        return False
    return abs(w - dialog_w) <= dialog_w * 0.35
