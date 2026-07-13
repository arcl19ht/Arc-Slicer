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
class DifficultyAudioAsset:
    rating_class: int
    filename: str
    path: Path
    usable: bool
    reason: str = ""


@dataclass(frozen=True)
class DifficultyMetadata:
    rating_class: int
    rating: int | None
    rating_plus: bool = False
    chart_designer: str = ""
    jacket_designer: str = ""
    title_override_base: str = ""


@dataclass(frozen=True)
class DifficultyDiscovery:
    available: tuple[DifficultyDefinition, ...]
    missing: tuple[DifficultyDefinition, ...]
    invalid: tuple[DifficultyFileIssue, ...]
    unknown_aff_filenames: tuple[str, ...]
    override_audio_assets: tuple[DifficultyAudioAsset, ...] = ()
    unknown_audio_filenames: tuple[str, ...] = ()

    @property
    def available_rating_classes(self) -> tuple[int, ...]:
        return tuple(item.rating_class for item in self.available)

    @property
    def usable_override_audio(self) -> tuple[DifficultyAudioAsset, ...]:
        available = set(self.available_rating_classes)
        return tuple(item for item in self.override_audio_assets if item.usable and item.rating_class in available)

    @property
    def orphan_override_audio(self) -> tuple[DifficultyAudioAsset, ...]:
        available = set(self.available_rating_classes)
        return tuple(item for item in self.override_audio_assets if item.rating_class not in available)

    def override_audio_for(self, rating_class: int) -> DifficultyAudioAsset | None:
        for item in self.override_audio_assets:
            if item.rating_class == rating_class:
                return item
        return None

    @property
    def warnings(self) -> tuple[str, ...]:
        available = set(self.available_rating_classes)
        warnings: list[str] = []
        for item in self.override_audio_assets:
            if item.rating_class not in available:
                warnings.append(f"孤立专属音源，不参与导出: {item.filename}")
            elif not item.usable:
                warnings.append(f"专属音源不可用: {item.filename} ({item.reason})")
        return tuple(warnings)


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
    override_audio_assets: list[DifficultyAudioAsset] = []

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

    for definition in STANDARD_DIFFICULTIES:
        path = song_dir / f"{definition.rating_class}.ogg"
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            override_audio_assets.append(DifficultyAudioAsset(
                definition.rating_class, path.name, path, False, "not_regular_file",
            ))
            continue
        try:
            with path.open("rb") as audio_file:
                audio_file.read(1)
        except OSError:
            override_audio_assets.append(DifficultyAudioAsset(
                definition.rating_class, path.name, path, False, "unreadable",
            ))
            continue
        override_audio_assets.append(DifficultyAudioAsset(definition.rating_class, path.name, path, True))

    unknown: list[str] = []
    unknown_audio: list[str] = []
    if song_dir.is_dir():
        try:
            for path in song_dir.iterdir():
                if path.suffix.lower() == ".aff" and path.name not in _STANDARD_FILENAMES:
                    unknown.append(path.name)
                if path.suffix.lower() == ".ogg" and path.name not in {"base.ogg", "0.ogg", "1.ogg", "2.ogg", "3.ogg", "4.ogg"}:
                    unknown_audio.append(path.name)
        except OSError:
            pass
    return DifficultyDiscovery(
        tuple(available), tuple(missing), tuple(invalid), tuple(sorted(unknown)),
        tuple(override_audio_assets), tuple(sorted(unknown_audio)),
    )


def is_multi_difficulty_song_dir(song_dir: Path) -> bool:
    song_dir = Path(song_dir)
    audio = song_dir / "base.ogg"
    if not song_dir.is_dir() or audio.is_symlink() or not audio.is_file():
        return False
    try:
        with audio.open("rb") as audio_file:
            audio_file.read(1)
    except OSError:
        return False
    return bool(discover_song_difficulties(song_dir).available)


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


def difficulty_metadata_from_legacy(legacy_data: Mapping | None) -> DifficultyMetadata:
    """Map the existing single FTR fields to ratingClass 2 without persisting assets."""
    data = legacy_data or {}
    rating = data.get("rating")
    if isinstance(rating, bool) or not isinstance(rating, int) or rating < 0:
        rating = None
    return DifficultyMetadata(
        rating_class=2,
        rating=rating,
        rating_plus=bool(data.get("rating_plus", data.get("ratingPlus", False))),
        chart_designer=str(data.get("chart_designer", data.get("chartDesigner", "")) or "").strip(),
        jacket_designer=str(data.get("jacket_designer", data.get("jacketDesigner", "")) or "").strip(),
        title_override_base=str(data.get("title_override_base", "") or "").strip(),
    )


def normalize_difficulty_metadata(
    rating_class: int,
    data: Mapping | DifficultyMetadata | None,
) -> DifficultyMetadata:
    definition = difficulty_for_rating_class(rating_class)
    if isinstance(data, DifficultyMetadata):
        if data.rating_class != definition.rating_class:
            raise ValueError("难度元数据 ratingClass 不一致")
        return data
    values = data or {}
    rating = values.get("rating")
    if rating in (None, ""):
        normalized_rating = None
    elif isinstance(rating, bool) or not isinstance(rating, int) or rating < 0:
        raise ValueError(f"ratingClass {rating_class} 的 rating 无效")
    else:
        normalized_rating = rating
    return DifficultyMetadata(
        rating_class=definition.rating_class,
        rating=normalized_rating,
        rating_plus=bool(values.get("rating_plus", values.get("ratingPlus", False))),
        chart_designer=str(values.get("chart_designer", values.get("chartDesigner", "")) or "").strip(),
        jacket_designer=str(values.get("jacket_designer", values.get("jacketDesigner", "")) or "").strip(),
        title_override_base=str(values.get("title_override_base", "") or "").strip(),
    )


def normalize_difficulty_metadata_map(
    data: Mapping | None,
    *,
    legacy_ftr_data: Mapping | None = None,
) -> dict[int, DifficultyMetadata]:
    out: dict[int, DifficultyMetadata] = {}
    for raw_rating_class, item in (data or {}).items():
        if isinstance(raw_rating_class, bool):
            raise ValueError("难度元数据键必须是 ratingClass")
        try:
            rating_class = int(raw_rating_class)
        except (TypeError, ValueError) as ex:
            raise ValueError("难度元数据键必须是 ratingClass") from ex
        if str(rating_class) != str(raw_rating_class) and not isinstance(raw_rating_class, int):
            raise ValueError("难度元数据键必须是整数")
        out[rating_class] = normalize_difficulty_metadata(rating_class, item)
    if 2 not in out and legacy_ftr_data is not None:
        out[2] = difficulty_metadata_from_legacy(legacy_ftr_data)
    return out


def serialize_difficulty_metadata_map(metadata: Mapping[int, DifficultyMetadata]) -> dict[str, dict]:
    return {
        str(rating_class): {
            "rating": item.rating,
            "rating_plus": item.rating_plus,
            "chart_designer": item.chart_designer,
            "jacket_designer": item.jacket_designer,
            "title_override_base": item.title_override_base,
        }
        for rating_class, item in sorted(metadata.items())
    }
