"""In-memory per-folder launch chains for same-directory exe wildcard saving."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_folder_chains: Dict[str, FolderChainState] = {}


@dataclass
class FolderChainState:
    """Tracks exes seen in one folder during the current app session."""

    folder_path: str
    exes_seen: List[str] = field(default_factory=list)
    has_confident_match: bool = False
    twitch_category: str = ""
    saved_exact_path: str = ""
    is_wildcard: bool = False


def normalize_folder_key(process_path: str) -> str:
    """Normalized absolute directory path for chain lookup."""
    return os.path.normcase(os.path.normpath(os.path.dirname(process_path)))


def folder_exe_wildcard_path(process_path: str) -> str:
    """Same-folder wildcard pattern covering direct *.exe siblings."""
    folder = os.path.dirname(os.path.normpath(process_path))
    return os.path.join(folder, "*.exe")


def get_chain_for_path(process_path: str) -> FolderChainState:
    """Return the folder chain for a process path, creating it if needed."""
    folder_key = normalize_folder_key(process_path)
    if folder_key not in _folder_chains:
        _folder_chains[folder_key] = FolderChainState(folder_path=folder_key)
    return _folder_chains[folder_key]


def note_exe_seen(process_path: str) -> FolderChainState:
    """Record that an executable in this folder received focus."""
    chain = get_chain_for_path(process_path)
    exe_name = os.path.basename(process_path)
    if exe_name and exe_name not in chain.exes_seen:
        chain.exes_seen.append(exe_name)
    return chain


def sync_chain_from_saved_app(chain: FolderChainState, detected_app: dict) -> None:
    """Mark the chain as matched when a saved detected-app entry applies."""
    category = (detected_app.get("twitch_category") or "").strip()
    if not category:
        return

    saved_path = detected_app.get("process_path") or ""
    chain.has_confident_match = True
    chain.twitch_category = category
    chain.is_wildcard = "*" in saved_path
    if not chain.is_wildcard:
        chain.saved_exact_path = saved_path


def mark_chain_after_save(
    chain: FolderChainState,
    saved_path: str,
    twitch_category: str,
) -> None:
    """Update chain state after persisting a detection result."""
    chain.has_confident_match = True
    chain.twitch_category = twitch_category
    chain.is_wildcard = "*" in saved_path
    if chain.is_wildcard:
        chain.saved_exact_path = ""
    else:
        chain.saved_exact_path = saved_path


def resolve_detection_save_target(
    chain: FolderChainState,
    process_path: str,
    window_title: str,
) -> Tuple[str, str]:
    """
    Decide whether to save an exact exe path or a same-folder *.exe wildcard.

    First confident match with 2+ exes seen in the chain saves a folder wildcard
    with an empty window title. A lone exe saves the exact path.
    """
    title = (window_title or "").strip()
    if len(chain.exes_seen) >= 2:
        return folder_exe_wildcard_path(process_path), ""
    return process_path, title


def should_skip_detection_for_chain(chain: FolderChainState) -> bool:
    """True when a prior match in this folder chain makes detection unnecessary."""
    return chain.has_confident_match and len(chain.exes_seen) >= 2


def chain_needs_wildcard_upgrade(chain: FolderChainState) -> bool:
    """True when a second same-folder exe should widen an exact save to wildcard."""
    return (
        chain.has_confident_match
        and not chain.is_wildcard
        and len(chain.exes_seen) >= 2
    )


def reset_folder_chains() -> None:
    """Clear all in-memory chains (for tests)."""
    _folder_chains.clear()


def cleanup_auto_excluded_for_wildcard_chain(chain: FolderChainState) -> int:
    """
    Drop auto-excluded entries for exes now covered by a folder wildcard save.

    Each exe name has at most one auto-excluded row; this removes up to one per
    exe seen in the chain. Mostly list hygiene — detected games override exclusions.
    """
    if len(chain.exes_seen) < 2 or not chain.is_wildcard:
        return 0

    from catswitch.excluded_apps import remove_from_auto_excluded_apps

    removed = remove_from_auto_excluded_apps(chain.exes_seen)
    return removed
