"""Energieverbruik per vraag.

ARCHITECTUUR-EN-WAARDEN.md §5/§7 noemt "verbruiksmeting per vraag" als
openstaande beslissing, met een expliciete eis: "Dit maakt de claim
controleerbaar in plaats van marketing." Dat is de reden voor twee methoden
in plaats van één, en voor het feit dat elke uitkomst een `bron` en
`dekking` meedraagt — een kaal getal zonder die twee is hier niet goed
genoeg, net zoals `docs/*.md` een meting zonder modelnaam niet als meting
telt.

TWEE METHODEN, GEEN NETWERKCALLS
---------------------------------
1. macmon (Apple Silicon, geen sudo, github.com/vladkens/macmon): meet
   ECHT SoC-vermogen (cpu+gpu+ane+geheugen) via samples tijdens de
   aanroep. Geverifieerd op deze machine: ~3W idle, 35-36W tijdens een
   Ollama-generatie — het cijfer volgt de daadwerkelijke belasting.
2. CodeCarbon (overal, offline-modus, geen sudo): schat via CPU-load en
   een TDP-tabel. Op Apple Silicon geeft dat GEEN bruikbaar cijfer —
   getest: een 3s sleep() gaf een HOGER cijfer dan drie echte
   Ollama-aanroepen, want CodeCarbon vindt hier geen GPU ("No GPU found";
   NVML is NVIDIA-only) en meet alleen CPU-load van dít Python-proces,
   niet van Ollama's proces. Op andere hardware (Linux+NVIDIA, of gewoon
   Intel) is dat cijfer wel zinniger, dus dit blijft de overal-werkende
   terugval — nooit de eerste keus op Apple Silicon.

De CO2-omrekening gebruikt CodeCarbon's eigen, bij het package
meegeleverde Nederlandse stroommixdata (267,6 g CO2/kWh, 2023) in plaats
van een zelfverzonnen constante — ook bij macmon-metingen, zodat er één
bronvermelding voor de omrekening is, niet twee losse aannames.
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

LAND_ISO = "NLD"
MACMON_INTERVAL_MS = 200

MACMON_BESCHIKBAAR = (
    platform.system() == "Darwin"
    and platform.machine() == "arm64"
    and shutil.which("macmon") is not None
)


def _co2_g_per_kwh(land_iso: str = LAND_ISO) -> float:
    """Leest CodeCarbon's meegeleverde stroommixdata — lokaal bestand, geen
    netwerkcall. Valt terug op een algemene EU-schatting als het package of
    het land ontbreekt, zodat een ontbrekende dependency dit niet laat
    crashen."""
    try:
        import codecarbon

        pad = Path(codecarbon.__file__).parent / "data/private_infra/global_energy_mix.json"
        with open(pad, encoding="utf-8") as f:
            mix = json.load(f)
        return float(mix[land_iso]["carbon_intensity"])
    except Exception:
        return 300.0  # ruwe EU-gemiddelde schatting; alleen als terugval


CO2_G_PER_KWH = _co2_g_per_kwh()


@dataclass
class Verbruik:
    energie_wh: float
    co2_g: float
    bron: str      # 'macmon' | 'codecarbon-schatting' | 'geen'
    dekking: str    # wat is meegenomen, in mensentaal — hoort bij elk cijfer


class _MacmonMeter:
    """Bemonstert SoC-vermogen op de achtergrond zolang de vraag loopt."""

    def __enter__(self) -> "_MacmonMeter":
        self._samples: list[float] = []
        self._start = time.monotonic()
        self._proces = subprocess.Popen(
            ["macmon", "pipe", "-s", "0", "-i", str(MACMON_INTERVAL_MS)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        self._draad = threading.Thread(target=self._lees, daemon=True)
        self._draad.start()
        return self

    def _lees(self) -> None:
        assert self._proces.stdout is not None
        for regel in self._proces.stdout:
            try:
                d = json.loads(regel)
                self._samples.append(float(d["all_power"]))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    def __exit__(self, *exc) -> None:
        self._duur_s = time.monotonic() - self._start
        self._proces.terminate()
        try:
            self._proces.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._proces.kill()
        self._draad.join(timeout=2)

    def resultaat(self) -> Verbruik:
        gem_watt = sum(self._samples) / len(self._samples) if self._samples else 0.0
        energie_wh = gem_watt * self._duur_s / 3600
        return Verbruik(
            energie_wh=energie_wh,
            co2_g=energie_wh / 1000 * CO2_G_PER_KWH,
            bron="macmon",
            dekking=(
                f"SoC-vermogen (cpu+gpu+neural engine+geheugen), "
                f"{len(self._samples)} samples · exclusief scherm/schijf/netwerk"
            ),
        )


class _CodeCarbonMeter:
    """Terugval voor niet-Apple-Silicon: schatting op basis van CPU-load."""

    def __enter__(self) -> "_CodeCarbonMeter":
        from codecarbon import OfflineEmissionsTracker

        self._tracker = OfflineEmissionsTracker(
            country_iso_code=LAND_ISO, log_level="error", save_to_file=False,
        )
        self._tracker.start()
        return self

    def __exit__(self, *exc) -> None:
        self._tracker.stop()

    def resultaat(self) -> Verbruik:
        data = self._tracker.final_emissions_data
        energie_wh = (data.energy_consumed * 1000) if data else 0.0
        return Verbruik(
            energie_wh=energie_wh,
            co2_g=(data.emissions * 1000) if data else 0.0,
            bron="codecarbon-schatting",
            dekking=(
                "schatting op basis van cpu-belasting van dit proces; "
                "geen gpu, dus vermoedelijk een onderschatting"
            ),
        )


class meet_verbruik:
    """Contextmanager: kiest macmon op Apple Silicon, anders CodeCarbon.

        with meet_verbruik() as m:
            ... doe het werk waarvan je het verbruik wilt weten ...
        resultaat = m.resultaat()
    """

    def __enter__(self) -> "meet_verbruik":
        self._impl = _MacmonMeter() if MACMON_BESCHIKBAAR else _CodeCarbonMeter()
        self._impl.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        self._impl.__exit__(*exc)

    def resultaat(self) -> Verbruik:
        return self._impl.resultaat()
