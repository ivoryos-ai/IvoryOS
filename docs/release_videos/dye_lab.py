"""
A dye-mixing self-driving lab, simulated: a liquid handler mixes red, yellow and blue dye in the
wells of a plate, and a plate reader measures their absorbance. The classic SDL loop is to find
the recipe that matches a target color.

The release videos record IvoryOS driving this deck. It needs no hardware, and each method logs
what it received, so a video shows the values the driver got (``40.0``, ``{450, 540, 630}``).

Run it on its own with ``python docs/release_videos/dye_lab.py``.
"""
import logging
import math
import random
import time
from typing import Dict, List, Literal, Optional, Set, Tuple

logger = logging.getLogger("dye_lab")

WELL_VOLUME_UL = 300

# Absorbance of each stock dye at the plate reader's filters (nm), undiluted: yellow absorbs blue
# light (450), red absorbs green (540) and blue absorbs red (630). Water dilutes them.
EXTINCTION = {
    "red": {450: 0.45, 540: 1.10, 630: 0.08},
    "yellow": {450: 1.20, 540: 0.20, 630: 0.04},
    "blue": {450: 0.10, 540: 0.30, 630: 1.30},
}
TARGETS = {"green": {"yellow": 60, "blue": 40}, "orange": {"red": 45, "yellow": 55}, "purple": {"red": 50, "blue": 50}}


def _absorbance(contents, wavelength):
    total = sum(contents.values()) or 1
    return sum(EXTINCTION.get(dye, {}).get(wavelength, 0.0) * ul for dye, ul in contents.items()) / total


class LiquidHandler:
    """Pipettes stock dyes into the wells of a 96-well plate."""

    def __init__(self, plate):
        self.plate = plate

    def dispense(self, recipe_ul: Dict[str, float], well: str = "A1") -> Dict[str, float]:
        """Dispense each dye of the recipe (uL) into a well, e.g. {"red": 40, "yellow": 60}. Returns what the well holds."""
        contents = self.plate.setdefault(well, {})
        if sum(contents.values()) + sum(recipe_ul.values()) > WELL_VOLUME_UL:
            raise ValueError(f"{well} would overflow ({WELL_VOLUME_UL} uL max)")
        for dye, ul in recipe_ul.items():
            contents[dye] = contents.get(dye, 0.0) + ul
        logger.info(f"dispense recipe_ul={recipe_ul!r} into {well}")
        time.sleep(0.5)
        return dict(contents)

    def mix(self, well: str = "A1", cycles: int = 3):
        """Aspirate and dispense the well a few times."""
        logger.info(f"mix {well} x{cycles}")
        time.sleep(0.3 * cycles)

    def dilute(self, wells: List[str], factor: float = 2.0):
        """Dilute each well with water, e.g. wells = A1, A2."""
        for well in wells:
            contents = self.plate.setdefault(well, {})
            contents["water"] = contents.get("water", 0.0) + sum(contents.values()) * (factor - 1)
        logger.info(f"dilute wells={wells!r} {factor}x")
        time.sleep(0.5)

    def move_to(self, xy_mm: Tuple[float, float] = (0.0, 0.0)):
        """Move the pipette head to a position on the deck, e.g. 12.5, 40."""
        logger.info(f"move_to xy_mm={xy_mm!r}")
        time.sleep(0.3)

    def clear_plate(self):
        """Start over with a clean plate."""
        self.plate.clear()
        logger.info("new plate")


class PlateReader:
    """Measures the absorbance of a well at its filter wavelengths."""

    def __init__(self, plate):
        self.plate = plate

    def read_absorbance(self, well: str = "A1", wavelengths_nm: Set[int] = {450, 540, 630},  # noqa: B006
                        shake: Optional[Literal["orbital", "linear"]] = None) -> Dict[str, float]:
        """Absorbance of a well at each wavelength, e.g. 450, 540, 630. Shake the plate first, or leave it blank."""
        contents = self.plate.get(well, {})
        reading = {f"A{nm}": round(_absorbance(contents, nm) + random.gauss(0, 0.01), 3) for nm in sorted(wavelengths_nm)}
        logger.info(f"read {well} wavelengths_nm={wavelengths_nm!r} shake={shake!r}: {reading}")
        time.sleep(0.5)
        return reading

    def color_distance(self, well: str = "A1", target: Literal["green", "orange", "purple"] = "green") -> float:
        """How far the well's color is from a target color (0 is a perfect match)."""
        contents, goal = self.plate.get(well, {}), TARGETS[target]
        distance = math.sqrt(sum((_absorbance(contents, nm) - _absorbance(goal, nm)) ** 2 for nm in (450, 540, 630)))
        distance = round(distance + abs(random.gauss(0, 0.005)), 3)
        logger.info(f"{well} is {distance} from {target}")
        return distance


plate = {}
liquid_handler = LiquidHandler(plate)
plate_reader = PlateReader(plate)

if __name__ == "__main__":
    import ivoryos

    ivoryos.run(__name__, logger=logger.name)
