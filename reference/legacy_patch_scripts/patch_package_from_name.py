# -*- coding: utf-8 -*-
"""Második javítás: a kiszerelés a névből is ellenőrizve.

A BENU `package_size` mezője önmagában is lehet téves. A
`Panactiv 100 mg/5 ml belsőleges szuszpenzió 100ml` termékoldalán a
kiszerelés mező értéke `5 ml`, holott a doboz 100 ml — a BENU az erősség
nevezőjét írta be kiszerelésnek. Ezért a kiszerelést külön kiolvassuk a
package_size mezőből és a névből is, és azonos mértékegység esetén a
nagyobbat vesszük, mert a doboz nem lehet kisebb annál, mint amit a
készítmény neve a végén megad.
"""
import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "build_normalized_catalog.py"

OLD = '''def parse_package_amount(package_size, name):
    source = normalize_space(" ".join(part for part in [package_size, name] if part))
    source = normalize_space(PACKAGE_STRENGTH_STRIP_RE.sub(" ", source))
'''

NEW = '''def parse_package_amount(package_size, name):
    """Kiszerelés a package_size mezőből ÉS a névből, a kettő közül a nagyobb.

    A BENU package_size mezője több terméknél az erősség nevezőjét tartalmazza
    (Panactiv 100 mg/5 ml ... 100ml -> `5 ml`). A készítmény nevének végén álló
    mennyiség ilyenkor megbízhatóbb.
    """
    from_pkg = _parse_package_source(package_size)
    from_name = _parse_package_source(name)
    if from_pkg[0] is not None and from_name[0] is not None:
        if from_pkg[1] == from_name[1]:
            return from_pkg if from_pkg[0] >= from_name[0] else from_name
        return from_name
    return from_pkg if from_pkg[0] is not None else from_name


def _parse_package_source(text):
    source = normalize_space(text or "")
    source = normalize_space(PACKAGE_STRENGTH_STRIP_RE.sub(" ", source))
'''


def main():
    src = TARGET.read_text(encoding="utf-8")
    if "_parse_package_source" in src:
        raise SystemExit("A második javítás már alkalmazva van.")
    if OLD not in src:
        raise SystemExit("Nem található a parse_package_amount eleje — előbb az 1. javítás kell.")
    bak = TARGET.with_suffix(f".py.{datetime.now():%Y%m%d_%H%M%S}.bak2")
    shutil.copy2(TARGET, bak)
    TARGET.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
    print(f"biztonsági másolat: {bak.name}")
    print("kész — parse_package_amount most a nevet is ellenőrzi")


if __name__ == "__main__":
    main()
