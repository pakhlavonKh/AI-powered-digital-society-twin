"""Reference table of Türkiye's 81 provinces and their İBBS (NUTS) codes.

This is classification metadata, not statistics. Plate codes follow the official province numbering
(also used by ISO 3166-2:TR); İBBS levels follow the 2002 statistical region classification used by
TÜİK (NUTS-1: 12 regions, NUTS-2: 26, NUTS-3: the 81 provinces). Codes are the identity of a province
everywhere in SocietyTwin; names are only matched (never trusted alone) when a source has no code.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

CLASSIFICATION = "İBBS (NUTS) 2002 statistical regions; province plate codes 01–81"

NUTS1_NAMES: dict[str, tuple[str, str]] = {
    "TR1": ("İstanbul", "Istanbul"),
    "TR2": ("Batı Marmara", "West Marmara"),
    "TR3": ("Ege", "Aegean"),
    "TR4": ("Doğu Marmara", "East Marmara"),
    "TR5": ("Batı Anadolu", "West Anatolia"),
    "TR6": ("Akdeniz", "Mediterranean"),
    "TR7": ("Orta Anadolu", "Central Anatolia"),
    "TR8": ("Batı Karadeniz", "West Black Sea"),
    "TR9": ("Doğu Karadeniz", "East Black Sea"),
    "TRA": ("Kuzeydoğu Anadolu", "Northeast Anatolia"),
    "TRB": ("Ortadoğu Anadolu", "Central East Anatolia"),
    "TRC": ("Güneydoğu Anadolu", "Southeast Anatolia"),
}

# (plate code, official name, NUTS-3 code, accepted alternative spellings)
_ROWS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("01", "Adana", "TR621", ()),
    ("02", "Adıyaman", "TRC12", ()),
    ("03", "Afyonkarahisar", "TR332", ("Afyon",)),
    ("04", "Ağrı", "TRA21", ()),
    ("05", "Amasya", "TR834", ()),
    ("06", "Ankara", "TR510", ()),
    ("07", "Antalya", "TR611", ()),
    ("08", "Artvin", "TR905", ()),
    ("09", "Aydın", "TR321", ()),
    ("10", "Balıkesir", "TR221", ()),
    ("11", "Bilecik", "TR413", ()),
    ("12", "Bingöl", "TRB13", ()),
    ("13", "Bitlis", "TRB23", ()),
    ("14", "Bolu", "TR424", ()),
    ("15", "Burdur", "TR613", ()),
    ("16", "Bursa", "TR411", ()),
    ("17", "Çanakkale", "TR222", ()),
    ("18", "Çankırı", "TR822", ()),
    ("19", "Çorum", "TR833", ()),
    ("20", "Denizli", "TR322", ()),
    ("21", "Diyarbakır", "TRC22", ()),
    ("22", "Edirne", "TR212", ()),
    ("23", "Elazığ", "TRB12", ()),
    ("24", "Erzincan", "TRA12", ()),
    ("25", "Erzurum", "TRA11", ()),
    ("26", "Eskişehir", "TR412", ()),
    ("27", "Gaziantep", "TRC11", ()),
    ("28", "Giresun", "TR903", ()),
    ("29", "Gümüşhane", "TR906", ()),
    ("30", "Hakkari", "TRB24", ("Hakkâri",)),
    ("31", "Hatay", "TR631", ()),
    ("32", "Isparta", "TR612", ()),
    ("33", "Mersin", "TR622", ("İçel", "Içel")),
    ("34", "İstanbul", "TR100", ()),
    ("35", "İzmir", "TR310", ()),
    ("36", "Kars", "TRA22", ()),
    ("37", "Kastamonu", "TR821", ()),
    ("38", "Kayseri", "TR721", ()),
    ("39", "Kırklareli", "TR213", ()),
    ("40", "Kırşehir", "TR715", ()),
    ("41", "Kocaeli", "TR421", ()),
    ("42", "Konya", "TR521", ()),
    ("43", "Kütahya", "TR333", ()),
    ("44", "Malatya", "TRB11", ()),
    ("45", "Manisa", "TR331", ()),
    ("46", "Kahramanmaraş", "TR632", ("K.Maraş", "K. Maraş")),
    ("47", "Mardin", "TRC31", ()),
    ("48", "Muğla", "TR323", ()),
    ("49", "Muş", "TRB22", ()),
    ("50", "Nevşehir", "TR714", ()),
    ("51", "Niğde", "TR713", ()),
    ("52", "Ordu", "TR902", ()),
    ("53", "Rize", "TR904", ()),
    ("54", "Sakarya", "TR422", ()),
    ("55", "Samsun", "TR831", ()),
    ("56", "Siirt", "TRC34", ()),
    ("57", "Sinop", "TR823", ()),
    ("58", "Sivas", "TR722", ()),
    ("59", "Tekirdağ", "TR211", ()),
    ("60", "Tokat", "TR832", ()),
    ("61", "Trabzon", "TR901", ()),
    ("62", "Tunceli", "TRB14", ()),
    ("63", "Şanlıurfa", "TRC21", ()),
    ("64", "Uşak", "TR334", ()),
    ("65", "Van", "TRB21", ()),
    ("66", "Yozgat", "TR723", ()),
    ("67", "Zonguldak", "TR811", ()),
    ("68", "Aksaray", "TR712", ()),
    ("69", "Bayburt", "TRA13", ()),
    ("70", "Karaman", "TR522", ()),
    ("71", "Kırıkkale", "TR711", ()),
    ("72", "Batman", "TRC32", ()),
    ("73", "Şırnak", "TRC33", ()),
    ("74", "Bartın", "TR813", ()),
    ("75", "Ardahan", "TRA24", ()),
    ("76", "Iğdır", "TRA23", ()),
    ("77", "Yalova", "TR425", ()),
    ("78", "Karabük", "TR812", ()),
    ("79", "Kilis", "TRC13", ()),
    ("80", "Osmaniye", "TR633", ()),
    ("81", "Düzce", "TR423", ()),
)


@dataclass(frozen=True)
class Province:
    code: str          # plate code, two digits ("06")
    name: str          # official Turkish name ("Ankara")
    nuts3: str         # "TR510"
    aliases: tuple[str, ...] = ()

    @property
    def nuts2(self) -> str:
        return self.nuts3[:4]

    @property
    def nuts1(self) -> str:
        return self.nuts3[:3]

    @property
    def iso(self) -> str:
        return f"TR-{self.code}"

    def as_dict(self) -> dict:
        return {"province_code": self.code, "province_name": self.name, "nuts3_code": self.nuts3,
                "nuts2_code": self.nuts2, "nuts1_code": self.nuts1, "nuts1_name": NUTS1_NAMES[self.nuts1][0],
                "nuts1_name_en": NUTS1_NAMES[self.nuts1][1], "iso_3166_2": self.iso}


PROVINCES: tuple[Province, ...] = tuple(Province(c, n, n3, a) for c, n, n3, a in _ROWS)
BY_CODE: dict[str, Province] = {p.code: p for p in PROVINCES}
BY_NUTS3: dict[str, Province] = {p.nuts3: p for p in PROVINCES}
NUTS2_CODES: tuple[str, ...] = tuple(sorted({p.nuts2 for p in PROVINCES}))
COUNTRY_CODE = "TR"


def name_key(name: str) -> str:
    """Case- and diacritic-insensitive key with Turkish dotted/dotless i handled before casefolding."""
    text = unicodedata.normalize("NFC", str(name)).strip().replace("İ", "i").replace("I", "ı").lower()
    text = text.translate(str.maketrans("çğıöşüâîû", "cgiosuaiu"))
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return "".join(c for c in text if c.isalnum())


_BY_NAME: dict[str, Province] = {}
for _p in PROVINCES:
    for _n in (_p.name, *_p.aliases):
        _BY_NAME[name_key(_n)] = _p


class UnknownProvince(ValueError):
    pass


def normalize_code(value: object) -> str:
    """Accept '6', '06', 6 or 'TR-06'; return the two-digit plate code. Never guesses from names."""
    text = str(value).strip().upper()
    if text.startswith("TR-"):
        text = text[3:]
    if text.endswith(".0"):
        text = text[:-2]
    if not text.isdigit():
        raise UnknownProvince(f"Not a province code: {value!r}")
    code = f"{int(text):02d}"
    if code not in BY_CODE:
        raise UnknownProvince(f"Province code out of range 01–81: {value!r}")
    return code


def province(value: object) -> Province:
    return BY_CODE[normalize_code(value)]


def by_name(name: str) -> Province:
    try:
        return _BY_NAME[name_key(name)]
    except KeyError:
        raise UnknownProvince(f"No province named {name!r}") from None


def resolve(value: object) -> Province:
    """Code first; a name is accepted only when it matches an official name or alias exactly (after normalisation)."""
    try:
        return province(value)
    except UnknownProvince:
        return by_name(str(value))


def provinces_in(geo_level: str, geo_code: str) -> tuple[Province, ...]:
    if geo_level == "province":
        return (province(geo_code),)
    if geo_level == "nuts3":
        return (BY_NUTS3[geo_code],)
    if geo_level == "nuts2":
        return tuple(p for p in PROVINCES if p.nuts2 == geo_code)
    if geo_level == "nuts1":
        return tuple(p for p in PROVINCES if p.nuts1 == geo_code)
    if geo_level == "country" and geo_code == COUNTRY_CODE:
        return PROVINCES
    raise UnknownProvince(f"Unknown geography {geo_level}:{geo_code}")


def containing_geographies(p: Province) -> list[tuple[str, str]]:
    """Geographies that contain a province, most specific first."""
    return [("province", p.code), ("nuts2", p.nuts2), ("nuts1", p.nuts1), ("country", COUNTRY_CODE)]
