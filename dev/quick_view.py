from datetime import date

from canvod.readers.gnss_specs.satellite_catalog import SatelliteCatalog

catalog = SatelliteCatalog.load()

_ref_date = date(2025, 1, 1)
_prefixes = {
    "G": "GPS",
    "R": "GLONASS",
    "E": "Galileo",
    "C": "BeiDou",
    "J": "QZSS",
    "I": "IRNSS/NavIC",
    "S": "SBAS",
}

_rows = []
for _p, _name in _prefixes.items():
    _prns = catalog.active_prns(_p, on_date=_ref_date)
    _rows.append(
        f"| {_name} (`{_p}`) | {len(_prns)} | `{', '.join(sorted(_prns)[:6])}`, ... |"
    )

print(_rows)

_ref = date(2025, 1, 1)
_examples = ["G01", "G02", "G32", "E01", "E02", "R01", "R24", "C01", "C06"]
_rows = []
for _prn in _examples:
    _svn = catalog.prn_to_svn(_prn, on_date=_ref)
    _rows.append(f"| `{_prn}` | `{_svn or '---'}` |")

print(_rows)
