from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineeringSymbol:
    """Single source of truth for UI and future report subscript formatting."""

    base: str
    subscript: str = ""

    @property
    def markup(self) -> str:
        return f"{self.base}{{{self.subscript}}}" if self.subscript else self.base

    @property
    def plain(self) -> str:
        return f"{self.base}_{self.subscript}" if self.subscript else self.base

    @property
    def runs(self) -> tuple[tuple[str, bool], ...]:
        return ((self.base, False), (self.subscript, True)) if self.subscript else ((self.base, False),)


SYMBOLS = {
    "N_MK": EngineeringSymbol("N", "Mk"),
    "T_K": EngineeringSymbol("T", "k"),
    "H_MIK": EngineeringSymbol("H", "Mik"),
    "R": EngineeringSymbol("R"),
    "Q_UK": EngineeringSymbol("Q", "uk"),
    "Q_SK": EngineeringSymbol("Q", "sk"),
    "Q_PK": EngineeringSymbol("Q", "pk"),
    "T_UK": EngineeringSymbol("T", "uk"),
    "G_P": EngineeringSymbol("G", "p"),
    "R_HA": EngineeringSymbol("R", "Ha"),
    "R_H": EngineeringSymbol("R", "H"),
    "K_MW": EngineeringSymbol("K", "Mw"),
    "H_0": EngineeringSymbol("h", "0"),
    "H_T": EngineeringSymbol("h", "t"),
    "B_0": EngineeringSymbol("b", "0"),
    "X_0A": EngineeringSymbol("x", "0a"),
    "NU_X": EngineeringSymbol("ν", "x"),
    "E_C": EngineeringSymbol("E", "c"),
    "E_S": EngineeringSymbol("E", "s"),
    "RHO_G": EngineeringSymbol("ρ", "g"),
}
