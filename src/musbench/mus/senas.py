"""Señas per the Fournier reglamento (nhfournier.es/como-jugar/mus).

"No se permite decir ni ensenar al companero las cartas que se tienen.
 No obstante, los companeros podran entenderse por medio de senas."

The seven Fournier señas, each with ONE fixed meaning (the wink covers two:
juego de 31, or -- a Juego no -- the best punto, 30). Don Naipe's blog adds
"ciego" (cerrar los ojos = ni pares ni juego) and "la bonita" (un beso = tres
reyes y un as); they are kept as flagged extras so you can prune them.
"""

SENAS = {
    # Fournier
    "muerde-el-labio-inferior":     ("dos reyes (para Grande)", "fournier"),
    "muerde-el-labio-hacia-un-lado": ("tres reyes", "fournier"),
    "saca-la-punta-de-la-lengua":   ("dos ases (para Chica)", "fournier"),
    "saca-la-lengua-hacia-un-lado": ("tres ases", "fournier"),
    "torcer-los-labios":            ("medias (tres iguales)", "fournier"),
    "elevar-las-cejas":             ("duples (dos parejas o cuatro iguales)", "fournier"),
    "guinar-el-ojo":                ("tengo 31 -- o, a Juego no, el mejor punto (30)", "fournier"),
    # Don Naipe extras (prune if you want Fournier-strict)
    "cerrar-los-ojos":              ("ciego: ni pares ni juego", "donnaipe"),
    "lanzar-un-beso":               ("la bonita: tres reyes y un as", "donnaipe"),
}


def _count(hand, rank) -> int:
    # mus-rank equivalence: tres counts as rey, dos counts as as
    group = {"rey": ("rey", "tres"), "as": ("as", "dos")}.get(rank, (rank,))
    return sum(1 for c in hand if c.rank in group)


def _truth(sena, hand, e) -> bool:
    t = e.hand_points(hand, e.card_points)
    p = e._pares_value(hand)[0]
    checks = {
        "muerde-el-labio-inferior":      _count(hand, "rey") == 2,
        "muerde-el-labio-hacia-un-lado": _count(hand, "rey") == 3,
        "saca-la-punta-de-la-lengua":    _count(hand, "as") == 2,
        "saca-la-lengua-hacia-un-lado":  _count(hand, "as") == 3,
        "torcer-los-labios":             p == 2,
        "elevar-las-cejas":              p == 3,
        "guinar-el-ojo":                 t == 31 or t == 30,
        "cerrar-los-ojos":               p == 0 and t not in e.juego_totals,
        "lanzar-un-beso":                _count(hand, "rey") == 3 and _count(hand, "as") == 1,
    }
    return checks[sena]


def is_valid_sena(text: str) -> bool:
    return str(text).strip().lower() in SENAS


def sena_truthful(sena, hand, engine) -> bool:
    entry = SENAS.get(str(sena).strip().lower())
    return bool(entry and _truth(sena.strip().lower(), hand, engine))


def vocabulary_for_prompt() -> str:
    return "\n".join(f'  "{g}" = {m}  [{src}]' for g, (m, src) in SENAS.items())
