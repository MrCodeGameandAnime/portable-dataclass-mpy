from dataclasses import dataclass, field


@dataclass
class Reading:
    value: int
    unit: str = "C"
    notes: list = field(default_factory=list)
