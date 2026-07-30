from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import (
    ensure_dir,
    file_sha256,
    fetch_url,
    find_project_root,
    html_to_text,
    infer_topics_and_tags,
    is_url,
    load_yaml,
    normalize_ref_key,
    normalize_title,
    normalize_remote_url,
    parse_wikilinks,
    parse_arxiv_id,
    parse_iso_datetime,
    program_root as common_program_root,
    research_root,
    slugify,
    skills_root as common_skills_root,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
    yaml_duplicate_key_issues,
)
from .ids import (
    UNIT_KIND_PREFIXES,
    build_unit_id,
    canonical_unit_id,
    canonical_unit_id_with_hash,
    compact_unit_slug,
    is_canonical_unit_id,
)
from .retrieval import rank_records
from .relations import *

from .paths import *
from .records import *
from .prefs import *
from .confirm import *
from .sources import *
from .index import *
from .git_ops import *
from .evidence import *
from .obsidian import *
