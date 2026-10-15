import math

class Mulberry32:
    """
    Deterministic 32-bit PRNG matching bitwise implementation in TypeScript.
    Guarantees 1e-9 parity between Python reference and browser Web Worker.
    """
    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF

    def next_float(self) -> float:
        self.state = (self.state + 0x6D2B79F5) & 0xFFFFFFFF
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
        t = (t ^ (t >> 14)) & 0xFFFFFFFF
        return float(t) / 4294967296.0

    def next_gaussian(self, mean: float = 0.0, std: float = 1.0) -> float:
        u1 = max(1e-12, self.next_float())
        u2 = self.next_float()
        z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        return mean + z0 * std
