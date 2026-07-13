"""Directory-driven chart difficulty discovery and selection compatibility."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class DifficultyDefinition:
    rating_class: int
    aff_filename: str
    display_name: str
    abbreviation: str


STANDARD_DIFFICULTIES = (
    DifficultyDefinition(0, "0.aff", "Past", "PST"),
    DifficultyDefinition(1, "1.aff", "Present", "PRS"),
    DifficultyDefinition(2, "2.aff", "Future", "FTR"),
    DifficultyDefinition(3, "3.aff", "Beyond", "BYD"),
    DifficultyDefinition(4, "4.aff", "Eternal", "ETR"),
)
DIFFICULTY_SELECTION_FIELD = "selected_difficulties"
_BY_RATING_CLASS = {item.rating_class: item for item in STANDARD_DIFFICULTIES}
_STANDARD_FILENAMES = frozenset(item.aff_filename for item in STANDARD_DIFFICULTIES)


@dataclass(frozen=True)
class DifficultyFileIssue:
    rating_class: int
    filename: str
    reason: str


@dataclass(frozen=True)
class DifficultyDiscovery:
    available: tuple[DifficultyDefinition, ...]
    missing: tuple[DifficultyDefinition, ...]
    invalid: tuple[DifficultyFileIssue, ...]
    unknown_aff_filenames: tuple[str, ...]

    @property
    def available_rating_classes(self) -> tuple[int, ...]:
        return tuple(item.rating_class for item in self.available)


class DifficultySelectionError(ValueError):
    """Raised when a persisted or requested difficulty selection is malformed."""


@dataclass(frozen=True)
class DifficultySelectionValidation:
    selected: tuple[int, ...]
    missing: tuple[int, ...]

    @property
    def ok(self) -> bool:
        return not self.missing


@dataclass(frozen=True)
class RestoredDifficultySelection:
    selected: tuple[int, ...]
    missing: tuple[int, ...]
    source: str
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.missing and bool(self.selected)


def difficulty_for_rating_class(rating_class: int) -> DifficultyDefinition:
    try:
        return _BY_RATING_CLASS[rating_class]
    except KeyError as ex:
        raise ValueError(f"未知难度 ratingClass: {rating_class}") from ex


def discover_song_difficulties(song_dir: Path) -> DifficultyDiscovery:
    """Inspect only standard chart names without modifying the source directory."""
    song_dir = Path(song_dir)
    available: list[DifficultyDefinition] = []
    missing: list[DifficultyDefinition] = []
    invalid: list[DifficultyFileIssue] = []

    for definition in STANDARD_DIFFICULTIES:
        path = song_dir / definition.aff_filename
        if not path.exists():
            missing.append(definition)
            continue
        if path.is_symlink() or not path.is_file():
            invalid.append(DifficultyFileIssue(definition.rating_class, definition.aff_filename, "not_regular_file"))
            continue
        try:
            with path.open("rb") as chart_file:
                chart_file.read(1)
        except OSError:
            invalid.append(DifficultyFileIssue(definition.rating_class, definition.aff_filename, "unreadable"))
            continue
        available.append(definition)

    unknown: list[str] = []
    if song_dir.is_dir():
        try:
            for path in song_dir.iterdir():
                if path.suffix.lower() == ".aff" and path.name not in _STANDARD_FILENAMES:
                    unknown.append(path.name)
        except OSError:
            pass
    return DifficultyDiscovery(tuple(available), tuple(missing), tuple(invalid), tuple(sorted(unknown)))


def is_multi_difficulty_song_dir(song_dir: Path) -> bool:
    song_dir = Path(song_dir)
    return song_dir.is_dir() and (song_dir / "base.ogg").is_file() and bool(discover_song_difficulties(song_dir).available)


def normalize_selected_difficulties(values: Iterable[int]) -> tuple[int, ...]:
    try:
        raw_values = tuple(values)
    except TypeError as ex:
        raise DifficultySelectionError("难度选择必须是整数序列") from ex
    if not raw_values:
        raise DifficultySelectionError("至少需要选择一个难度")
    normalized: set[int] = set()
    for value in raw_values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise DifficultySelectionError("难度选择只能包含 0 到 4 的整数")
        if value not in _BY_RATING_CLASS:
            raise DifficultySelectionError(f"难度选择超出范围: {value}")
        normalized.add(value)
    return tuple(sorted(normalized))


def validate_selected_difficulties(
    selected_difficulties: Iterable[int],
    available_difficulties: Iterable[int | DifficultyDefinition],
) -> DifficultySelectionValidation:
    selected = normalize_selected_difficulties(selected_difficulties)
    available = {
        item.rating_class if isinstance(item, DifficultyDefinition) else item
        for item in available_difficulties
    }
    missing = tuple(item for item in selected if item not in available)
    return DifficultySelectionValidation(selected, missing)


def default_selected_difficulties(available_difficulties: Iterable[int | DifficultyDefinition]) -> tuple[int, ...]:
    available = {
        item.rating_class if isinstance(item, DifficultyDefinition) else item
        for item in available_difficulties
    }
    return tuple(rating_class for rating_class in _BY_RATING_CLASS if rating_class in available)


def restore_selected_difficulties(
    slides_data: Mapping | None,
    available_difficulties: Iterable[int | DifficultyDefinition],
    *,
    is_new_song: bool = False,
) -> RestoredDifficultySelection:
    """Apply new-song and legacy-FTR migration rules without hiding invalid data."""
    data = slides_data if isinstance(slides_data, Mapping) else {}
    available = default_selected_difficulties(available_difficulties)
    if DIFFICULTY_SELECTION_FIELD not in data:
        selected = available if is_new_song else ((2,) if 2 in available else available)
        source = "new" if is_new_song else "legacy"
        error = "没有可用标准难度" if not selected else ""
        return RestoredDifficultySelection(selected, (), source, error)
    try:
        validation = validate_selected_difficulties(data[DIFFICULTY_SELECTION_FIELD], available)
    except DifficultySelectionError as ex:
        return RestoredDifficultySelection((), (), "saved", str(ex))
    error = ""
    if validation.missing:
        names = "、".join(difficulty_for_rating_class(item).aff_filename for item in validation.missing)
        error = f"已选难度文件缺失: {names}"
    return RestoredDifficultySelection(validation.selected, validation.missing, "saved", error)


def serialize_selected_difficulties(slides_data: Mapping | None, selected_difficulties: Iterable[int]) -> dict:
    """Return a song-level slides payload with a normalized explicit selection."""
    data = dict(slides_data or {})
    data[DIFFICULTY_SELECTION_FIELD] = list(normalize_selected_difficulties(selected_difficulties))
    return data
